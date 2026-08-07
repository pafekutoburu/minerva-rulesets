#!/usr/bin/env python3
"""
STUN 验活引擎 —— `build.py` 的探测仪器,同时是独立的 CLI 探针。

它做一件事:向候选服务器发一个真实的 STUN Binding Request(RFC 5389,20 字节 UDP 包),
看有没有**合法的 STUN 响应**回来。这是 `sets/network/stun.list` 收录判据的仪器:
清单收哪些、不收哪些,由这里的实测决定,不再照抄上游的候选池。

🔴 **在维护者本机上,这个探测器预期全部 timeout —— 不是脚本坏了**(2026-08-07 实测):
本机的 Surge 正在拦 STUN(fake-IP 段 198.18.x + `PROTOCOL,STUN,REJECT` 双层),
被测物恰好就是测试仪要拦的东西。本地只能验「脚本不崩、分类正确」,
**真判决只能来自 CI runner**(workflow_dispatch 跑一轮读日志)。
`build.py` 的仪器故障保险因此也保护了本地误跑:哨兵全灭 ⇒ 拒绝采信,清单一个字节不动。

CLI 用法:
  python3 scripts/stun_check.py                     # 哨兵逐台 + 候选池随机采样 ~40 台
  python3 scripts/stun_check.py host:port [...]     # 指定目标逐台探测
"""

import os
import random
import socket
import struct
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MAGIC_COOKIE = 0x2112A442

STUN_CANDIDATES_URL = \
    "https://raw.githubusercontent.com/pradt2/always-online-stun/master/candidates.txt"

# 仪器哨兵:大运营商 / 参考实现的 STUN 服务,拿来回答「**我的 UDP 出站坏没坏**」——
# 哨兵全灭时,该怀疑的是仪器不是世界(Cloudflare 都不理我 ⇒ 我这条网断了)。
# 逐台注明选择理由与「在不在候选池里」(2026-08-07 实测):
SENTINELS = (
    # 不在候选池 —— 纯仪器探针,和被测集合零重叠,读数最干净。
    ("stun.cloudflare.com", 3478),
    # 在候选池 —— 全球部署最广的 STUN;⚠️ 它只开 19302/19305,没有 3478。
    ("stun.l.google.com", 19302),
    # 在候选池 —— stunprotocol.org 是 RFC 参考实现(stuntman)的官方演示站。
    ("stunserver2024.stunprotocol.org", 3478),
    # 在候选池 —— Nextcloud 官方;⚠️ 池里唯一走 443 端口的。
    ("stun.nextcloud.com", 443),
)


def parse_candidates(text):
    """
    上游 `candidates.txt` → `{host: {port, …}}`。

    **探测与建清单共用这一份 parser,不许分叉出第二份过滤逻辑** ——
    上游文件里有注释行(`# stun.sipgate.net:3478`)、裸 IP 与域名混排,
    两份过滤逻辑迟早会在某一行上给出两个答案。
    过滤判据(与旧 `build_stun` 逐字一致,host 集合不许因抽函数而变):
      · 空行与 `#` 注释行跳过;
      · 裸 IP 丢弃 —— `DOMAIN,` 只认域名,IPv6 字面量(strip 掉 `[]` 后仍含 `:`)同理;
      · host 一律小写。

    ⚠️ 端口只为**探测**服务,清单本身仍是剥端口的域名。多端口是 load-bearing:
    候选池里 5 个 Google 域名**只开 19302/19305、根本没有 3478**(2026-08-07 实测),
    全按 3478 探会把用得最广的五台判死 —— 所以任一端口有响应就算活。
    「无端口默认 3478」纯属防御:635 行里 0 行无端口(2026-08-07 实测),这条路从未走过。
    """
    targets = {}
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        host, sep, port_text = s.rpartition(":")
        if not sep:
            host, port_text = s, ""
        host = host.strip().strip("[]").lower()
        if not host or all(c in "0123456789." for c in host) or ":" in host:
            continue
        try:
            port = int(port_text) if port_text else 3478
        except ValueError:
            port = 3478
        if not 0 < port < 65536:
            port = 3478
        targets.setdefault(host, set()).add(port)
    return targets


def binding_request():
    """RFC 5389 Binding Request:type=0x0001 · length=0 · magic cookie · 12 字节随机 TID。"""
    tid = os.urandom(12)
    return struct.pack("!HHI", 0x0001, 0, MAGIC_COOKIE) + tid, tid


def is_valid_response(data, tid):
    """
    只校验到**头部**为止,四项:长度 ≥ 20 · 类型 · magic cookie · TID 相符。

    · 类型收 0x0101(Binding Success)**也收 0x0111(Binding Error)** ——
      错误响应同样证明那里跑着一台 STUN 服务器,而「它是 STUN 服务器」
      正是这份**拦截**清单的收录语义(清单是拿来挡的,不是拿来用的)。
    · **TID 必须校验**:拒掉中间盒垃圾与劫持页乱回 —— 没有 TID 对照,
      任何往这个端口回包的东西都会被当成活的。
    · **不解析 XOR-MAPPED-ADDRESS**:属性层解析只添失败面,不添判据价值。
    · ⚠️ RFC 3489 老服务器不认 magic cookie,会把我们的 cookie+TID 当成
      16 字节旧式 TID **原样回显** ⇒ 恰好通过全部四项校验。这是巧合,
      但结果正确(老 STUN 服务器也是 STUN 服务器)—— 别把这个「巧合」修掉。
    """
    if len(data) < 20:
        return False
    (msg_type,) = struct.unpack("!H", data[:2])
    if msg_type not in (0x0101, 0x0111):
        return False
    return data[4:8] == struct.pack("!I", MAGIC_COOKIE) and data[8:20] == tid


def probe(host, port, timeout=3.0):
    """
    单点探测 → `"alive" | "dns" | "timeout" | "unreachable"`。

    四类只有 `alive` 参与收录判定,其余三类是**观测用的分类计数**(CI 日志里看趋势):
    dns 涨 = 域名批量到期;unreachable 涨 = runner 网络形态变了。
    ⚠️ 已知测量偏差:GitHub 托管 runner **没有 IPv6 出站**,AAAA-only 的候选会一直判
    `dns`/`unreachable` —— 上游同在 runner 上测,偏差与上游一致,池里此类预计 0-2 台,不修。
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except OSError:
        return "dns"
    family, _type, proto, _canon, addr = infos[0]
    request, tid = binding_request()
    try:
        with socket.socket(family, socket.SOCK_DGRAM, proto) as sock:
            sock.sendto(request, addr)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "timeout"
                sock.settimeout(remaining)
                try:
                    data, _peer = sock.recvfrom(2048)
                except TimeoutError:
                    return "timeout"
                if is_valid_response(data, tid):
                    return "alive"
                # 收到了包但不是合法 STUN 响应(中间盒垃圾)⇒ 在窗口内继续等真的。
    except OSError:
        return "unreachable"


def _sweep(targets, concurrency, timeout):
    """一趟全量扫。同一 host 的多个端口**串行**试(多端口 host 只有个位数),任一响应即活。"""
    def one(host):
        results = []
        for port in sorted(targets[host]):
            verdict = probe(host, port, timeout)
            if verdict == "alive":
                return host, "alive"
            results.append(verdict)
        return host, results[0]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return dict(pool.map(one, sorted(targets)))


def check_liveness(targets, concurrency=50, timeout=3.0):
    """
    `{host: {port,…}}` → `{host: 判定}`,两趟扫。

    🔴 **第二趟在第一趟完全结束之后**对未活者整体重扫 —— 不是原地立即重发:
    立即重发撞上的是同一阵丢包,隔开一整趟才能把瞬时抖动和真死区分开。
    并发用 threads 而不是 asyncio:asyncio 的 `getaddrinfo` 走默认 executor
    (2 核 runner 上只有 6 个 worker),六百个 DNS 解析会被串行化,
    死域名的解析超时反过来主导总时长;阻塞 socket + 线程池没有这个坑,代码也短一半。
    """
    verdicts = _sweep(targets, concurrency, timeout)
    retry = {h: targets[h] for h, v in verdicts.items() if v != "alive"}
    if retry:
        verdicts.update(_sweep(retry, concurrency, timeout))
    return verdicts


def tally(verdicts):
    """分类计数,固定顺序方便日志逐轮对比。"""
    counts = {"alive": 0, "dns": 0, "timeout": 0, "unreachable": 0}
    for v in verdicts.values():
        counts[v] = counts.get(v, 0) + 1
    return counts


# ---------------------------------------------------------------- CLI 探针

def _probe_and_print(host, port, note=""):
    verdict = probe(host, port)
    print(f"  {host}:{port:<6} {verdict:<12} {note}")
    return verdict


def _cli(argv):
    if argv:
        print("指定目标探测:")
        for arg in argv:
            host, sep, port_text = arg.rpartition(":")
            if not sep:
                host, port_text = arg, "3478"
            _probe_and_print(host.strip("[]"), int(port_text))
        return 0

    print("哨兵探测(全灭 = 这台机器的 UDP 出站坏了,不是服务器死了):")
    sentinel_alive = sum(
        _probe_and_print(h, p, "· 哨兵") == "alive" for h, p in SENTINELS)
    print(f"  ⇒ 哨兵 {sentinel_alive}/{len(SENTINELS)} 活。"
          + ("UDP 出站可用。" if sentinel_alive else
             "🔴 UDP 出站不可用(本机被 Surge 拦是预期的,见文件头注释)。"))

    print("候选池随机采样(响应率只作情报,不是判决):")
    req = urllib.request.Request(
        STUN_CANDIDATES_URL, headers={"User-Agent": "minerva-rulesets-builder"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        targets = parse_candidates(resp.read().decode("utf-8", errors="replace"))
    sample_hosts = random.sample(sorted(targets), min(40, len(targets)))
    verdicts = check_liveness({h: targets[h] for h in sample_hosts})
    counts = tally(verdicts)
    print(f"  采样 {len(sample_hosts)} 台(候选池共 {len(targets)} 域名):{counts}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
