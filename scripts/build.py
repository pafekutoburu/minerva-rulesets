#!/usr/bin/env python3
"""
minerva-rulesets 生成器。

产出两样东西:
  sets/**/*.list   ← **自建层**。从一手来源生成(APNIC 注册数据 / 厂商官方文档)。
  manifest.json    ← app 与其他使用者消费的目录,覆盖自建层 + 索引层。

**索引层(indexed)只写地址,不托管内容。** 它的条目来自 `indexed/sources.json`(手工策展),
本脚本会去拉一次上游**只为了数条数、看格式、算内容指纹**,拉回来的内容随即丢弃、
一个字节都不落进本仓。这样既能给使用者一个真实的条数,又不产生任何再分发行为。

🔴 **索引层的「新鲜度」是自己记出来的,不是问上游要的**(2026-08-07 立此规矩):
`raw.githubusercontent.com` **根本不发 `Last-Modified`**,而生态里绝大多数清单都托管在那儿 ——
只靠这个头,11 条索引里 10 条永远没有时间。两条看着更聪明的路都实测排除了:
  · **查 GitHub API 的文件提交时间** —— `Loyalsoldier/surge-rules` 的 release 是**每日 force-push
    重建的孤儿分支**,任何文件的提交历史都只有 1 条、日期恒为今天 ⇒ 9 条会永远显示「刚更新」。
  · **解析上游文件头里的自称时间** —— 逐源格式不同(Loyalsoldier 压根没有表头),
    逐源正则太脆,而且只多救得到一条。
所以改用**内容指纹**:每轮存一份 sha256,**指纹没变就沿用上次的时间**,变了才动。
这和自建层 `write_list` 那条「内容没变不重写」是同一条纪律的两种写法 ——
「跑过一次」不等于「内容变过」,而使用者想知道的永远是后者。

硬约束:
  1. **只读网络与仓内文件**,绝不读任何本机路径。
  2. **路径里永不出现策略名。** `sets/media/netflix.list` ✅ / `rules/Proxy/Netflix.list` ❌ ——
     后者把「Netflix 走代理」这个**一个人的决定**焊进了资产本身,对另一个国家的用户从根上不成立。
     清单只回答「这些是什么」,「走哪」由使用者在自己的配置里决定。
  3. 只用标准库,CI 上不需要 pip install。
"""

import hashlib
import ipaddress
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO, "manifest.json")
INDEXED_SOURCES = os.path.join(REPO, "indexed", "sources.json")

APNIC_URL = "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"
STUN_CANDIDATES_URL = \
    "https://raw.githubusercontent.com/pradt2/always-online-stun/master/candidates.txt"
BASE_URL = "https://raw.githubusercontent.com/pafekutoburu/minerva-rulesets/refs/heads/main/"

# 🔴 **层级是数据,不是目录。**
# 直觉上该把镜像内容放进 `mirrored/`,让路径自己说明层级、不可能标错。但**不行**:
# 这些 URL 会被写进使用者的配置,路径一变,所有引用它的人当场断掉 ——
# 那正是我们在老仓上要花力气避免的迁移债。**URL 稳定优先于目录自解释。**
# 于是层级放在这张表里:不在表上的 `sets/` 文件都是 authored。
#
# `sets/network/stun.list` 为什么是 mirrored 而不是 authored:
#   它的内容 100% 来自 pradt2/always-online-stun 的候选池(MIT,明许再分发),
#   我们只做了「剥端口、去裸 IP、排序」这种机械变换 —— **没有任何属于我们的判断**。
#   标成 authored 就是假背书,和本项目刚撤掉的那三条假蓝勾是同一个错误。
#   等我们有了自己的收录判据(自己验活、自己从厂商文档补、自己剔死条目),它才配升 authored。
MIRRORED_SETS = {
    "sets/network/stun.list": {
        "repository": "pradt2/always-online-stun",
        "homepage": "https://github.com/pradt2/always-online-stun",
        "license": "MIT",
        "listURL": STUN_CANDIDATES_URL,
    },
}

# 每份清单的**人话说明** —— 目录是给人读的,`cn-asn` 这种文件名不算说明。
# 索引层的说明写在 `indexed/sources.json` 里,这张表只管 `sets/`。
# ⚠️ 说的是「这是什么」,**不是「它该走哪」** —— 那是使用者自己的决定(见 README 第一原则)。
SET_SUMMARIES = {
    "sets/region/cn-ipv4.list":
        "分配给中国大陆组织的 IPv4 网段,来自 APNIC 每日发布的注册数据。"
        "⚠️ Surge 内建的 GEOIP,CN 已经覆盖了大部分同类需求,这份的价值在于来源可查。",
    "sets/region/cn-ipv6.list":
        "分配给中国大陆组织的 IPv6 网段,来自 APNIC 每日发布的注册数据。",
    "sets/region/cn-asn.list":
        "分配给中国大陆组织的自治系统号(ASN)。ASN 是「一整家网络运营商」的编号,"
        "比按 IP 段判断更粗但更稳,来自 APNIC 每日发布的注册数据。",
    "sets/network/stun.list":
        "公开 STUN 服务器的域名。STUN 是设备用来发现自己公网 IP 的协议,浏览器里的 WebRTC 会用它。"
        "拦掉这些域名可以减少一类 IP 泄漏,代价是某些语音/视频通话可能受影响。",
}

NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

# Surge 能直接消费的规则前缀。索引层的格式闸门用它 —— 见 `check_indexed`。
SURGE_RULE_PREFIXES = (
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD", "DOMAIN-SET",
    "IP-CIDR", "IP-CIDR6", "IP-ASN", "IP-SUFFIX", "GEOIP",
    "PROCESS-NAME", "USER-AGENT", "URL-REGEX", "PROTOCOL",
    "DEST-PORT", "SRC-PORT", "SRC-IP", "IN-PORT", "SUBNET", "RULE-SET",
    "AND", "OR", "NOT",
)

# 🔴 **Surge 引用远程清单有两条不同的指令,不能混用**(2026-07-29 G7 实测判决,见 API-NOTES R9-D):
#   RULE-SET   —— 文件里每行是**完整规则**(`DOMAIN-SUFFIX,example.com`)
#   DOMAIN-SET —— 文件里每行是**裸域名**(`.example.com`),前导点 = 后缀匹配(含子域)
# 生态里两种都很常见(anti-AD 是前者,Loyalsoldier 全是后者),写错指令 Surge 不会报错,
# 只是那份清单**一条都匹配不上** —— 又一个「东西在但不起作用」的静默失败。
DIRECTIVES = ("RULE-SET", "DOMAIN-SET")


# ---------------------------------------------------------------- 一手来源:APNIC

def fetch_apnic():
    """APNIC 每日发布的注册数据。这是**一手权威来源**,不是谁的策展。"""
    req = urllib.request.Request(APNIC_URL, headers={"User-Agent": "minerva-rulesets-builder"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_apnic(text):
    """
    行格式:
      apnic|CN|ipv4|1.0.1.0|256|20110414|allocated     ← 第 5 列是**地址数量**,不是前缀长度
      apnic|CN|ipv6|2001:250::|35|20000426|allocated    ← 第 5 列**就是**前缀长度
      apnic|CN|asn|3460|1|20020801|allocated            ← 第 5 列是连续 ASN 的个数

    ⚠️ 三种类型三种含义 —— 拿行数当条数会错得离谱(一行 asn 最多能是 3072 个)。
    """
    v4, v6, asn = [], [], []
    for line in text.splitlines():
        if line.startswith("#") or "|CN|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 7 or parts[1] != "CN":
            continue
        kind, start, value, status = parts[2], parts[3], parts[4], parts[6]
        # 只要真正分配出去的;summary 行与保留段跳过。
        if status not in ("allocated", "assigned"):
            continue
        try:
            if kind == "ipv4":
                first = ipaddress.IPv4Address(start)
                last = ipaddress.IPv4Address(int(first) + int(value) - 1)
                # ⚠️ 数量不一定是 2 的幂、起点也不一定对齐 ⇒ 一个分配可能要拆成多条 CIDR。
                #    用标准库汇总,别手写位运算(手写最容易在非对齐段上悄悄算错)。
                v4.extend(ipaddress.summarize_address_range(first, last))
            elif kind == "ipv6":
                v6.append(ipaddress.IPv6Network(f"{start}/{value}", strict=False))
            elif kind == "asn":
                asn.extend(range(int(start), int(start) + int(value)))
        except (ipaddress.AddressValueError, ValueError) as exc:
            print(f"  ⚠️ 跳过一行无法解析的 APNIC 数据: {line!r} ({exc})", file=sys.stderr)
    return v4, v6, asn


# ---------------------------------------------------------------- 写清单

def write_list(rel_path, title, source_note, lines):
    """
    返回 `(条数, 这一轮有没有重写)`。**后者 manifest 要用** ——
    git log 看不到还没提交的改动,不告诉它就会把「今天变的」记成「上次变的」。

    🔴 **表头里绝不写 Policy。** 见模块头注释第 2 条。

    🔴 **内容没变就不重写。** 表头里有生成时间,无脑重写会让每天的定时任务都产生一条
    「只改了时间戳」的提交 —— 而 manifest 的 updatedAt 取的是 git 最后提交时间,
    于是**每份清单都会永远显示「刚刚更新」**,新鲜度这个功能当场作废。
    那等于把「这份东西半年没变过」说成「它天天在更新」。
    (这不是假想:上一版管线 CI 第一次跑绿时就是这么干的,当天就被抓出来了。)
    """
    path = os.path.join(REPO, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            existing = [s for s in (line.strip() for line in f)
                        if s and not s.startswith("#")]
        if existing == lines:
            print(f"  {rel_path}: {len(lines)} 条(内容未变,保持原文件)")
            return len(lines), False

    body = "\n".join(lines)
    header = (
        f"# {title}\n"
        f"# Source: {source_note}\n"
        f"# Generated: {NOW}\n"
        f"# Rules: {len(lines)}\n"
        f"#\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body + "\n")
    print(f"  {rel_path}: {len(lines)} 条")
    return len(lines), True


def build_sets():
    """返回 `(每份清单的条数, 这一轮被重写过的清单)`。后者见 `write_list` 的注释。"""
    print("[1/3] 从 APNIC 生成自建清单…")
    v4, v6, asn = parse_apnic(fetch_apnic())
    src = "APNIC delegated-apnic-latest(注册机构一手数据)"
    counts, rewritten = {}, set()

    def record(rel, result):
        counts[rel], changed = result
        if changed:
            rewritten.add(rel)

    record("sets/region/cn-ipv4.list", write_list(
        "sets/region/cn-ipv4.list", "中国大陆 IPv4 地址段", src,
        [f"IP-CIDR,{n},no-resolve" for n in sorted(v4, key=lambda n: int(n.network_address))],
    ))
    record("sets/region/cn-ipv6.list", write_list(
        "sets/region/cn-ipv6.list", "中国大陆 IPv6 地址段", src,
        [f"IP-CIDR6,{n},no-resolve" for n in sorted(v6, key=lambda n: int(n.network_address))],
    ))
    record("sets/region/cn-asn.list", write_list(
        "sets/region/cn-asn.list", "中国大陆自治系统号(ASN)", src,
        [f"IP-ASN,{a},no-resolve" for a in sorted(set(asn))],
    ))
    record("sets/network/stun.list", build_stun())
    return counts, rewritten


def build_stun():
    """
    公开 STUN 服务器的主机名。**内容来自 pradt2/always-online-stun**(MIT),见 MIRRORED_SETS 注释。
    返回值同 `write_list` —— `(条数, 这一轮有没有重写)`。

    上游是 `host:port` 一行一条,Surge 的 `DOMAIN-SET` 吃不了带端口的行,
    所以这里剥掉端口、去掉裸 IP(`DOMAIN,` 只认域名)、去重排序,产出 `RULE-SET` 格式。
    """
    req = urllib.request.Request(
        STUN_CANDIDATES_URL, headers={"User-Agent": "minerva-rulesets-builder"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    hosts = set()
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        host = s.rsplit(":", 1)[0].strip().strip("[]").lower()
        # 裸 IP 进不了 `DOMAIN,` —— 那是域名规则。丢掉,不硬塞。
        if not host or all(c in "0123456789." for c in host) or ":" in host:
            continue
        hosts.add(host)

    return write_list(
        "sets/network/stun.list", "公开 STUN 服务器域名",
        "pradt2/always-online-stun candidates.txt(MIT)—— 剥端口去重,内容为上游所有",
        [f"DOMAIN,{h}" for h in sorted(hosts)],
    )


# ------------------------------------------------- 上一版 manifest(索引层新鲜度的对照)

def previous_manifest():
    """
    上一次已提交的 manifest。**索引层的新鲜度全靠它做对照** —— 没有它就只能问上游要时间,
    而上游多半给不出(见模块头注释)。读不到就当没有,照常继续:第一次跑、或者文件坏了,
    结果是「这一轮所有索引条目都算第一次见到」,**只会退回「不知道」,不会编出一个时间**。
    """
    if not os.path.exists(MANIFEST):
        return {}
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def entries_by_path(manifest):
    """按 `path` 索引 —— 索引层的 `path` 就是它的 `listURL`,是稳定键。
    策展表里换了地址 = 换了一条,历史对不上是**对的**,不该硬认。"""
    return {e["path"]: e for e in manifest.get("entries", []) if e.get("path")}


def parse_stamp(value):
    """把 manifest 里的时间串读回来比大小。读不懂就当没有 —— 不猜。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------- 索引层

def rule_count_text(text):
    """
    真正会成为规则的行数。⚠️ **分母不是物理行数** —— 注释与空行不是规则。
    判据与 app 侧 `RuleSetHealth.ruleCount` 一致,两边不许分叉。
    """
    n = 0
    for raw in text.splitlines():
        s = raw.strip()
        if s and not s.startswith("#") and not s.startswith(";") and not s.startswith("//"):
            n += 1
    return n


def rule_count(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return rule_count_text(f.read())


def title_of(path):
    """
    清单的人话标题 = 表头第一行注释(`write_list` 写的就是它)。
    读不到才退回文件名 —— `cn-asn` 这种给人看是不合格的,目录是给人读的。
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = raw.strip()
            if s.startswith("#"):
                text = s.lstrip("#").strip()
                if text:
                    return text
            elif s:
                break
    return os.path.splitext(os.path.basename(path))[0]


def first_rule_line(text):
    for raw in text.splitlines():
        s = raw.strip()
        if s and not s.startswith("#") and not s.startswith(";") and not s.startswith("//"):
            return s
    return ""


def check_indexed(entry):
    """
    去上游拉一次,**只为了数条数、验格式、算指纹、读 Last-Modified**;内容随即丢弃,不落盘。

    返回 `(条数, 上游自称的时间, 内容指纹)`;拉不到时三个全是 `None` ——
    **「这一轮没测到」和「测到了是空的」必须能分辨**,见下。

    🔴 两类失败必须分开处理,合并就会说谎:
      · **拉不到**(网络/404)⇒ 警告,**不写 ruleCount**。绝不写 0 ——
        「不知道」和「空的」是两回事,本项目在别处栽过三次。app 的体检会如实显示「拉不到」。
      · **拉到了但不是 Surge 格式** ⇒ **硬错误,CI 变红**。这意味着上游改了产物形态,
        我们指过去的地址已经不能用了 —— 这正是索引层唯一需要人工介入的时刻,不许静默放过。
    """
    url = entry["listURL"]
    req = urllib.request.Request(url, headers={"User-Agent": "minerva-rulesets-builder"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            last_modified = resp.headers.get("Last-Modified")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  ⚠️ {entry['id']}: 拉不到({exc})—— 不写 ruleCount,绝不写 0", file=sys.stderr)
        return None, None, None

    head = first_rule_line(text)
    directive = entry.get("directive", "RULE-SET")
    token = head.split(",", 1)[0].strip().upper()
    looks_like_rule = token in SURGE_RULE_PREFIXES
    # 裸域名:没有逗号、不含空格。DOMAIN-SET 的一行就长这样(前导点可有可无)。
    looks_like_domain = ("," not in head) and (" " not in head) and ("." in head)

    ok = looks_like_rule if directive == "RULE-SET" else looks_like_domain
    if not ok:
        actual = "RULE-SET(整条规则)" if looks_like_rule else \
                 "DOMAIN-SET(裸域名)" if looks_like_domain else "两种都不像"
        print(
            f"::error::索引条目 {entry['id']} 的上游格式与声明的指令对不上。\n"
            f"  地址: {url}\n"
            f"  声明: {directive} · 实际看起来是: {actual}\n"
            f"  首条非注释行: {head[:120]!r}\n"
            f"  ⇒ 🔴 指令写错 Surge **不会报错**,那份清单只是一条都匹配不上。\n"
            f"     要么改 directive,要么把这条撤出索引层。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    stamp = None
    if last_modified:
        try:
            stamp = parsedate_to_datetime(last_modified).astimezone(
                timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError):
            stamp = None  # 上游给了个读不懂的时间 ⇒ 不写,别编。
    # 指纹拿**原始字节**算 —— 解码时的 `errors="replace"` 会把坏字节折成同一个替换符,
    # 拿解码后的文本算,两份不同的内容可能得到同一个指纹。
    return rule_count_text(text), stamp, hashlib.sha256(raw).hexdigest()


def load_indexed():
    """索引层条目来自手工策展的 `indexed/sources.json` —— 我们策展的是目录,不是内容。"""
    if not os.path.exists(INDEXED_SOURCES):
        return []
    with open(INDEXED_SOURCES, encoding="utf-8") as f:
        return json.load(f).get("entries", [])


def freshness_of(entry_id, digest, upstream_stamp, previous):
    """
    这一条**内容上次真的变了**是什么时候 —— 返回 `(时间, 要存下来的指纹, 日志用的一句话)`。

    🔴 **判定顺序即判据**,四种情形的后果完全不同,合并任意两种都会说谎:

      1. **这一轮没拉到** ⇒ 原样保留上次的指纹与时间。
         抹掉指纹会让下一轮把它当「第一次见到」——**一次网络抖动就清空这条的新鲜度历史**,
         而且下一轮还会顺手把「刚开始看」说成「刚更新」。什么都没测到时,什么都别动。
      2. **指纹和上次一样** ⇒ **沿用上次的时间,一动不动**(上次是「没有」就继续「没有」)。
         哪怕上游的 `Last-Modified` 往前跳了也不跟 —— 那是「它重新生成了一份一模一样的」,
         不是「内容变了」。**这一条就是整个功能的地基**:少了它,日更型上游会永远显示「刚更新」。
      3. **指纹变了**(且我们有历史指纹)⇒ 内容确实动了。优先用上游自称的 `Last-Modified`
         (它比我们的观察更精确),但**倒退或指向未来的自称一律不信**,退回本次运行时间 ——
         我们至少确切知道「这一刻它和上次不一样了」,误差不超过一个运行间隔。
      4. **第一次见到**(没有历史指纹,含本次迁移)⇒ 上游给了时间就用,**没给就不写**。
         🔴 **绝不拿「现在」顶替**:「我们刚开始看它」和「它刚更新过」是两回事。
         这条会自愈 —— 内容一变就落到情形 3,等到的是真话。
    """
    prev = previous.get(entry_id) or {}
    prev_hash, prev_stamp = prev.get("contentHash"), prev.get("updatedAt")

    if digest is None:                                   # 1. 没测到
        return prev_stamp, prev_hash, "这轮没拉到,沿用上次"
    if prev_hash == digest:                              # 2. 内容没变
        return prev_stamp, digest, "内容未变"
    if prev_hash:                                        # 3. 内容变了
        now, claimed, floor = parse_stamp(NOW), parse_stamp(upstream_stamp), parse_stamp(prev_stamp)
        credible = claimed is not None and claimed <= now and (floor is None or claimed > floor)
        return (upstream_stamp if credible else NOW), digest, \
            "内容有变动(上游自称)" if credible else "内容有变动(本轮观察到)"
    return upstream_stamp, digest, \
        "第一次见到" + ("" if upstream_stamp else ",上游没给时间 ⇒ 暂不写")  # 4.


def build_indexed(previous):
    print("[2/3] 校验索引层上游…")
    out = []
    for entry in load_indexed():
        count, upstream_stamp, digest = check_indexed(entry)
        stamp, digest, note = freshness_of(entry["listURL"], digest, upstream_stamp, previous)
        item = {
            "path": entry["listURL"],          # 索引层不在本仓,path 就是它的真实地址
            "displayName": entry["displayName"],
            "category": entry.get("category", ""),
            "tags": entry.get("tags", []),
            "layer": "indexed",
            # 🔴 引用它要用哪条指令。消费方**必须**读这个字段,不能一律当 RULE-SET ——
            #    写错不报错、只是一条都匹配不上(见 DIRECTIVES 头注释)。
            "directive": entry.get("directive", "RULE-SET"),
            "summary": entry.get("summary", ""),
            "upstream": dict(entry["upstream"], listURL=entry["listURL"]),
        }
        if count is not None:
            item["ruleCount"] = count
        if stamp:
            item["updatedAt"] = stamp
        # 指纹是**管线自己的记忆**,app 不消费它(解码器只取已知键,多这个字段无影响)。
        # 存在 manifest 里而不另开状态文件:manifest 本来就是已提交的状态,
        # 再开一份就会有两份真相,而且它俩迟早对不上。
        if digest:
            item["contentHash"] = digest
        print(f"  {entry['id']}: {count if count is not None else '拉不到'} 条"
              f" · {note} · {stamp or '时间未知'}")
        out.append(item)
    return out


# ---------------------------------------------------------------- manifest

def git_last_commit_times():
    """
    每个文件最后一次被改动的时间。
    ⚠️ 一次 `git log` 走完,不要每个文件 spawn 一次。
    """
    proc = subprocess.run(
        ["git", "-C", REPO, "log", "--pretty=format:@%cI", "--name-only"],
        capture_output=True, text=True,
    )
    # 仓库还没有任何提交(第一次跑)⇒ 拿不到时间。**不写 updatedAt,绝不用「现在」顶替** ——
    # 「还没提交过」和「刚更新过」是两回事,后者是句假话。
    if proc.returncode != 0:
        print("  ⚠️ 读不到 git 历史,本轮不写 updatedAt(不拿「现在」顶替)", file=sys.stderr)
        return {}
    out = proc.stdout
    times, current = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            current = line[1:]
        elif line and current and line not in times:
            times[line] = current  # 第一次出现 = 最近一次改动
    return times


def assert_unchanged_content_keeps_its_time(old_entries, entries):
    """
    🔴 机器判据:**内容指纹没变,更新时间就不许动。**

    这是「新鲜度」整个功能的地基。一旦哪轮改动让没变过的清单跟着刷新时间,每份清单都会
    永远显示「刚更新」,这一列当场作废 —— **本项目已经栽过一次**(上一版管线内容没变也提交,
    CI 第一次跑绿当天就被抓出来)。判据写在这儿,是为了不再依赖谁记得住注释。

    ⚠️ 它只管「没变的不许动」这一个方向。内容真变了时间该怎么定,是 `freshness_of` 的事。
    """
    lied = []
    for e in entries:
        prev = old_entries.get(e["path"], {})
        if not prev.get("contentHash") or prev["contentHash"] != e.get("contentHash"):
            continue                       # 没有历史 / 内容真变了 —— 时间该动就动
        if prev.get("updatedAt") != e.get("updatedAt"):
            lied.append((e["path"], prev.get("updatedAt"), e.get("updatedAt")))
    if not lied:
        return
    print(
        "::error::下列条目的内容指纹没变,更新时间却动了 —— 这会把「它半年没动过」"
        "说成「刚更新」:\n  " + "\n  ".join(
            f"{p}: {before!r} → {after!r}" for p, before, after in lied),
        file=sys.stderr,
    )
    raise SystemExit(1)


def build_manifest(generated_counts, indexed_entries, old, rewritten):
    print("[3/3] 生成 manifest.json…")
    times = git_last_commit_times()
    entries = []

    sets_root = os.path.join(REPO, "sets")
    for dirpath, _, files in os.walk(sets_root):
        for name in sorted(files):
            if not name.endswith(".list"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, REPO)
            entry = {
                "path": rel,
                "displayName": title_of(full),
                # `sets/` 的一级目录**就是**分类 —— 这是新结构的定义,不需要任何猜测。
                # (上一版对着 605 个镜像文件用文件名正则猜分类,69% 猜不出来。
                #  那个数字本身就是「镜像层没被策展过」的诚实信号;新仓没有那一层。)
                "category": rel.split("/")[1] if len(rel.split("/")) > 2 else "",
                "tags": [],
                "ruleCount": generated_counts.get(rel) or rule_count(full),
                "layer": "mirrored" if rel in MIRRORED_SETS else "authored",
                "summary": SET_SUMMARIES.get(rel, ""),
                # 自建层一律产出完整规则行(`IP-CIDR,…` / `DOMAIN-SUFFIX,…`)⇒ 恒为 RULE-SET。
                # 仍然如实写出来,好让消费方**一律读这个字段**,不必按层去猜。
                "directive": "RULE-SET",
            }
            # 🔴 **一律用 git 最后提交时间。** 用「本次生成时间」的话,每天跑完都是「刚更新」,
            #    哪怕 APNIC 半年没动过数据。**「跑过一次」不等于「内容变过」**,
            #    而使用者想知道的是后者。配合 write_list 的「内容没变不重写」,
            #    git 时间才真正等于「这份内容上次变化的时间」。
            # ⚠️ 拿不到就**不写这个字段**(全新文件尚未提交),绝不用「现在」顶替。
            #
            # ⚠️ **本轮刚重写的文件是唯一的例外**:git log 看到的是**上一次**提交,
            #    而这次的改动还没提交 ⇒ 会把「今天变的」记成「上次变的」,慢一整轮才回填
            #    (实测:cn-asn.list 在 08-06 那轮被重写,那轮的 manifest 却记着 07-29)。
            #    方向虽然保守(只会说得更旧),但它就是不准。`write_list` 已经知道自己有没有
            #    重写,直接用它 —— 这不是「拿现在顶替」:我们**确切知道**内容这一刻变了。
            stamp = NOW if rel in rewritten else times.get(rel)
            if stamp:
                entry["updatedAt"] = stamp
            # 🔴 标了 mirrored 就必须说清内容是谁的 —— 只标层级不标出处等于没标。
            if rel in MIRRORED_SETS:
                entry["upstream"] = MIRRORED_SETS[rel]
            entries.append(entry)

    entries.sort(key=lambda e: e["path"])
    entries.extend(indexed_entries)

    # 🔴 机器判据:**每一条都必须有人话说明。** 目录是给人读的 ——
    #    没有说明的条目在使用者那边就是一个文件名,他无从判断该不该用。
    #    新加清单时忘了写说明,CI 直接红,不许悄悄发出去。
    missing = [e["path"] for e in entries if not e.get("summary")]
    if missing:
        print(
            "::error::下列条目缺人话说明(sets/ 写进 SET_SUMMARIES,索引层写进 "
            "indexed/sources.json 的 summary):\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )
        raise SystemExit(1)

    assert_unchanged_content_keeps_its_time(entries_by_path(old), entries)

    manifest = {
        "schemaVersion": 1,
        "baseURL": BASE_URL,
        "generatedAt": NOW,
        "entries": entries,
    }

    # 🔴 只有 generatedAt 变了就不重写 —— 与 write_list 同一条纪律。
    #    否则每天都会产生一条纯时间戳提交,把仓库历史变成噪音。
    if old and {k: v for k, v in old.items() if k != "generatedAt"} == \
       {k: v for k, v in manifest.items() if k != "generatedAt"}:
        print(f"  条目 {len(entries)}(内容未变,保持原文件)")
        return

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")

    by_layer = {}
    for e in entries:
        by_layer[e["layer"]] = by_layer.get(e["layer"], 0) + 1
    uncategorized = sum(1 for e in entries if not e["category"])
    print(f"  条目 {len(entries)} · {by_layer} · 未归类 {uncategorized}")


def main():
    # 🔴 **在任何写入之前**读一次上一版 manifest:索引层的新鲜度全靠它做「内容变没变」的对照,
    #    而 build_sets 会改 sets/ 下的文件。只读一次,两个地方共用。
    old = previous_manifest()
    counts, rewritten = build_sets()
    indexed_entries = build_indexed(entries_by_path(old))
    build_manifest(counts, indexed_entries, old, rewritten)
    print("完成。")


if __name__ == "__main__":
    main()
