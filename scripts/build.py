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
import math
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import stun_check

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(REPO, "manifest.json")
INDEXED_SOURCES = os.path.join(REPO, "indexed", "sources.json")
# STUN 验活记忆(管线私有,app 不消费)。为什么是独立文件而不是 manifest 字段,见 load_stun_state。
STUN_STATE = os.path.join(REPO, "state", "stun-liveness.json")

APNIC_URL = "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"

# 微软**官方文档化**的端点服务。`clientrequestid` 是微软要求的调用方标识,
# 这里是一个**写死的常量 GUID** —— 不是本机生成、不携带任何本机信息。
O365_URL = ("https://endpoints.office.com/endpoints/worldwide"
            "?clientrequestid=b10c5ed1-bad1-445f-b386-b919946339a7")

# GitHub 官方端点清单(一手)。
GITHUB_META_URL = "https://api.github.com/meta"

# 🔴 GitHub `meta` 里只取这几个键,**这是一次取舍,理由必须写进 summary**:
#   `actions` 一个键就 7297 条 —— 那是 **Azure 的地址段**,不是 GitHub 自己的服务端点,
#   照单全收会把清单撑爆而且答非所问。`codespaces`(191)/`copilot`(17) 同理:
#   都是别人家的云,只是 GitHub 在上面跑东西。
# ⚠️ 这是「这些地址**是什么**」的判断,不是「它**该走哪**」—— 不违第一原则。
GITHUB_META_KEYS = ("web", "api", "git", "packages", "pages")
BASE_URL = "https://raw.githubusercontent.com/pafekutoburu/minerva-rulesets/refs/heads/main/"

# 🔴 **层级是数据,不是目录。**
# 直觉上该把镜像内容放进 `mirrored/`,让路径自己说明层级、不可能标错。但**不行**:
# 这些 URL 会被写进使用者的配置,路径一变,所有引用它的人当场断掉 ——
# 那正是我们在老仓上要花力气避免的迁移债。**URL 稳定优先于目录自解释。**
# 于是层级放在这张表里:不在表上的 `sets/` 文件都是 authored。
#
# 现状:**空表**(表与 build_manifest 的 mirrored 分支保留 —— 将来还会有镜像条目)。
# 上一个也是唯一一个成员是 `sets/network/stun.list`(2026-07-29 至 2026-08-07):
#   当时它的内容 100% 照抄 pradt2/always-online-stun 的候选池,「收哪些不收哪些」
#   全是上游的判断,标 authored 就是假背书。2026-08-07 起收录判据自建
#   (CI 每轮发真实 STUN Binding Request 验活,连续 7 天无响应才移除,见 build_stun),
#   「收哪些」从此由我们的实测裁决 —— 标签跟着现实走,它这才配升 authored。
MIRRORED_SETS = {}

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
        "拦掉这些域名可以减少一类 IP 泄漏,代价是某些语音/视频通话可能受影响。"
        "候选名单来自 pradt2/always-online-stun(MIT),但收录判据是 Minerva 自己的:"
        "CI 每天向每台候选与在册服务器发真实 STUN 请求,只收 7 天内有响应的 —— "
        "死掉的 STUN 服务器不会泄漏你的 IP,留着只是虚胖;哪天它复活了,次日就会回到清单里。",
    "sets/microsoft/microsoft-365.list":
        "Microsoft 365(Outlook、Teams、OneDrive、Office 网页版等)用到的服务域名,"
        "取自微软官方发布的端点清单,每天自动跟随。"
        "⚠️ 这份只有域名;微软同时公布的 IP 段暂未收录。"
        "另有两个域名模式(通配符在中间)Surge 表达不了,已排除。",
    "sets/dev/github.list":
        "GitHub 自家服务(网页、API、git 传输、Packages、Pages)的 IP 段,取自 GitHub 官方接口,每天自动跟随。"
        "⚠️ 只有 IP 段没有域名 —— 官方没发布域名清单,我们不替它编。"
        "⚠️ 不含 Actions/Codespaces/Copilot:那几项跑在 Azure 上,官方给的是 Azure 的地址段(七千多条),"
        "不是 GitHub 自己的服务端点。",
    "sets/ai/openai.list":
        "OpenAI(ChatGPT 网页版与 API)用到的服务域名,照 OpenAI 官方网络文档整理。"
        "🔴 手工维护,不自动跟随上游变更 —— 官方那份是网页文档、机器读不了。"
        "看「新鲜度」就知道它多久没对照过了。",
    "sets/ai/anthropic.list":
        "Anthropic(Claude 网页版与 API)用到的服务域名与官方公布的固定 IP 段,照 Anthropic 官方文档整理。"
        "🔴 手工维护,不自动跟随上游变更。官方明确写了这些 IP「不会无通知变更」,"
        "但域名部分仍需人工对照,看「新鲜度」判断新旧。",
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


def build_sets(old_manifest):
    """返回 `(每份清单的条数, 这一轮被重写过的清单)`。后者见 `write_list` 的注释。
    `old_manifest` 只有 STUN 用 —— 它的状态判据要知道上一版里自己是不是已经 authored。"""
    print("[1/3] 从一手来源生成自建清单…")
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
    record("sets/network/stun.list", build_stun(old_manifest))
    record("sets/microsoft/microsoft-365.list", build_microsoft365())
    record("sets/dev/github.list", build_github())
    # ⚠️ `sets/ai/` 下那两份是**手工维护**的,不在这里生成 —— 它们由人对着厂商官方文档整理,
    #    管线只负责在 manifest 里如实记录它们的条数与最后改动时间。见 SET_SUMMARIES。
    return counts, rewritten


# ------------------------------------------------- STUN:验活收录(authored 的判据所在)

STUN_LIST = "sets/network/stun.list"
# 记忆窗口:连续 7 天无响应才移除。窗口只为抑制 UDP 丢包抖动 —— 死掉的 STUN 服务器
# 不会泄漏任何人的 IP(泄漏需要它真的响应),所以**多留几天没有安全代价**;
# 而候选池每天全量重验,被移除的哪天复活了,次日就回清单。
STUN_MEMORY_DAYS = 7
# 候选条数下限(2026-08-07 实测 621 个域名)—— 只防「拉到半截文件」这种残缺穿透,
# 上游整个拉不到时 urlopen 自己就抛(= CI 红,现有语义)。
STUN_CANDIDATE_FLOOR = 400
# 活数绝对下限 = 上游 valid_hosts 当时 86 条的一半(2026-08-07)。首轮没有自己的基数,拿它兜底。
STUN_ALIVE_FLOOR = 40
# 状态陈旧上限:上一轮状态比这还老,说明状态更新没被提交(workflow 忘了 add state/),
# 或者 CI 停跑了很久 —— 两种都值得人看一眼,而且此时 7 天记忆已经不可信。
STUN_STATE_MAX_AGE_DAYS = 10


def load_stun_state():
    """
    STUN 验活记忆:`{host: {"lastAliveAt": …, "ports": […]}}` + 上一轮的探测规模。

    🔴 **为什么是独立文件而不是 manifest 字段**(对照 build_indexed 里 contentHash 的注释):
    那条成例的实质是「**同一个事实不许记两处**」—— contentHash 若另开文件,manifest 里
    还有一份,两份真相迟早漂移。验活记忆是**全新的事实、只记这一处**,不违背成例的精神;
    而塞进 manifest 的实害有两层:manifest 是 app 每轮下载的消费品,几百台主机的状态
    全是它永不读的字节;更糟的是这份记忆**按构造每轮都变**(活主机的时间戳刷新),
    会把 manifest 自己「没变不重写」的安静纪律当场顶穿。
    读坏了就当没有(照 parse_stamp 的规矩,不猜)—— 后果只是记忆归零、清单退回「当轮活着的」,
    判据本身不会说谎。
    """
    if not os.path.exists(STUN_STATE):
        return {}
    try:
        with open(STUN_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"  ⚠️ {STUN_STATE}: 读不懂,当作没有(记忆归零,不猜)", file=sys.stderr)
        return {}


def save_stun_state(hosts, probed, alive):
    """`sort_keys` + 固定缩进落盘 —— 字节确定性,diff 才只反映事实变化。"""
    os.makedirs(os.path.dirname(STUN_STATE), exist_ok=True)
    state = {
        "note": "管线私有:STUN 验活记忆(scripts/build.py 读写),app 不消费此文件。",
        "schemaVersion": 1,
        "lastRun": {"at": NOW, "probed": probed, "alive": alive},
        "hosts": hosts,
    }
    with open(STUN_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def read_stun_members():
    """上轮清单成员(从现 stun.list 的 `DOMAIN,` 行读)。文件不在就是空 —— 第一轮。"""
    path = os.path.join(REPO, STUN_LIST)
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8", errors="replace") as f:
        return {s[len("DOMAIN,"):].strip().lower()
                for s in (line.strip() for line in f)
                if s.startswith("DOMAIN,")}


def assert_stun_members_recently_alive(members, hosts_state, cutoff):
    """🔴 机器判据:清单每一条都必须在记忆里有 7 天内的响应记录。
    今天它按构造成立;它守的是**未来**——谁要是改了成员计算(比如退回照抄候选池)
    而忘了验活判据,CI 立刻红。"""
    stale = [h for h in members
             if parse_stamp(hosts_state.get(h, {}).get("lastAliveAt")) is None
             or parse_stamp(hosts_state[h]["lastAliveAt"]) < cutoff]
    if not stale:
        return
    print(
        f"::error::stun.list 里出现了 {STUN_MEMORY_DAYS} 天内没有响应记录的条目 —— "
        "收录判据是「我们自己测到它活着」,不是「上游说它存在」:\n  "
        + "\n  ".join(sorted(stale)), file=sys.stderr)
    raise SystemExit(1)


def assert_stun_membership_bounded(members, candidates, prev_members):
    """🔴 机器判据:清单 ⊆ 候选池 ∪ 上轮成员。成员只能从这两处来 ——
    冒出别的来源,说明有人绕过了收录判据。"""
    orphans = members - set(candidates) - prev_members
    if not orphans:
        return
    print(
        "::error::stun.list 里出现了既不在候选池、也不是上轮成员的条目:\n  "
        + "\n  ".join(sorted(orphans)), file=sys.stderr)
    raise SystemExit(1)


def assert_stun_state_committed(old_manifest, prev_state):
    """
    🔴 机器判据:验活记忆必须真的**在被提交**(抓「写了从不提交」)。

    威胁模型:workflow 的 `git add` 路径漏了 `state/` ⇒ 每轮都写状态、从不提交 ⇒
    CI 每轮 checkout 到的都是陈旧记忆 ⇒ 7 天窗口静默失效、清单退化成「当日活着的」——
    **每一轮孤立看都自洽,别的判据全抓不到。**两道检查:
      1. 状态文件必须被 git 跟踪(升级 commit 之后恒真);
      2. 上一轮状态的 `lastRun.at` 不得老过 {STUN_STATE_MAX_AGE_DAYS} 天。

    ⚠️ 门控在「上一版 manifest 里 STUN 已是 authored」:升级那一轮(上一版还是 mirrored)
    状态文件尚不存在 —— 首份记忆只能由 CI 生成(维护者本机测不了 STUN,见 stun_check.py),
    那一轮跳过检查是**设计**,不是漏网。
    """
    old_layer = entries_by_path(old_manifest).get(STUN_LIST, {}).get("layer")
    if old_layer != "authored":
        return
    tracked = subprocess.run(
        ["git", "-C", REPO, "ls-files", "--error-unmatch", os.path.relpath(STUN_STATE, REPO)],
        capture_output=True)
    if tracked.returncode != 0:
        print("::error::STUN 已是 authored,但 state/stun-liveness.json 不在 git 里 —— "
              "验活记忆从未被提交,7 天窗口是空话。", file=sys.stderr)
        raise SystemExit(1)
    last_at = parse_stamp((prev_state.get("lastRun") or {}).get("at"))
    if last_at and parse_stamp(NOW) - last_at > timedelta(days=STUN_STATE_MAX_AGE_DAYS):
        print(
            f"::error::上一轮 STUN 验活记忆停在 {last_at.isoformat()},距今超过 "
            f"{STUN_STATE_MAX_AGE_DAYS} 天 —— 要么 workflow 忘了提交 state/(记忆在静默失效),"
            "要么 CI 停跑了很久(记忆已不可信)。两种都需要人看一眼。", file=sys.stderr)
        raise SystemExit(1)


def build_stun(old_manifest):
    """
    公开 STUN 服务器域名 —— **authored:收哪些、不收哪些由本仓自己的实测裁决**(2026-08-07 起)。
    返回值同 `write_list` —— `(条数, 这一轮有没有重写)`。

    候选名单来自 pradt2/always-online-stun 的 candidates.txt(MIT,如实署名),
    但那只是**线索来源**;收录判据在这里:
      清单 = (候选池 ∪ 上轮成员) 中 {STUN_MEMORY_DAYS} 天内对真实 STUN 请求有过响应的域名。

    🔴 **∪ 上轮成员是拍板过的取舍**(2026-08-07):上游把一台**还活着**的服务器从候选池
    清理掉时,我们不跟着放行 —— 别人的清单卫生不该变成使用者的泄漏回归;
    成员退出的唯一途径是**我们自己**连续 {STUN_MEMORY_DAYS} 天没测到它活。

    🔴 **仪器判决在一切写入之前**(哨兵全灭 / 活数腰斩 ⇒ CI 红、本轮什么都不改):
    「这轮没测到」≠「服务器死了」—— 和索引层「这轮没拉到就什么都别动」同一条纪律,
    只是这里测的是 UDP,坏得更常见。风险不对称也写在这儿:多拦一台死服务器代价为零,
    错删一台活的 = 泄漏窗口重开,所以一切拿不准的偏向都往「多留 / 不动」倒。

    P0 判决(2026-08-07,run 31168486861):GitHub runner 的 UDP 出站**可用** ——
    哨兵 3/4 活(dns 失败那台是域名自己的事),候选池采样 40 台 16 台有合法响应。
    维护者本机则**测不了**(自家 Surge 在拦 STUN,见 stun_check.py 头注释),
    所以本地跑到这儿会在哨兵判决处红着退出 —— 那是保险在工作,不是 bug。
    """
    req = urllib.request.Request(
        stun_check.STUN_CANDIDATES_URL, headers={"User-Agent": "minerva-rulesets-builder"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    candidates = stun_check.parse_candidates(text)
    if len(candidates) < STUN_CANDIDATE_FLOOR:
        print(
            f"::error::候选池只解析出 {len(candidates)} 个域名(下限 {STUN_CANDIDATE_FLOOR},"
            "2026-08-07 实测 621)—— 多半是拉到了半截文件,本轮不采信。", file=sys.stderr)
        raise SystemExit(1)

    prev_state = load_stun_state()
    prev_hosts = prev_state.get("hosts") or {}
    prev_members = read_stun_members()
    assert_stun_state_committed(old_manifest, prev_state)

    # 全集 = 候选 ∪ 上轮成员。在册但已被上游剔掉的,端口用记忆里的(上游那份已经没有它了)。
    targets = {h: set(ps) for h, ps in candidates.items()}
    for h in prev_members:
        if h not in targets:
            known = (prev_hosts.get(h) or {}).get("ports") or [3478]
            targets[h] = set(known)

    # 仪器判决第一道:哨兵。全灭 ⇒ 坏的是我们的 UDP 出站,不是全世界的 STUN 服务器。
    sentinel_verdicts = stun_check.check_liveness(
        {h: {p} for h, p in stun_check.SENTINELS}, concurrency=len(stun_check.SENTINELS))
    sentinel_alive = sum(v == "alive" for v in sentinel_verdicts.values())
    print(f"  stun: 哨兵 {sentinel_alive}/{len(stun_check.SENTINELS)} 活")
    if sentinel_alive == 0:
        print(
            "::error::STUN 哨兵全灭(Cloudflare/Google 都不响应)⇒ 判定仪器故障,"
            "本轮验活不采信、清单与记忆一字不动。在维护者本机这是预期结果(Surge 在拦);"
            "在 CI 上出现,说明 runner 的 UDP 出站坏了。", file=sys.stderr)
        raise SystemExit(1)

    verdicts = stun_check.check_liveness(targets)
    counts = stun_check.tally(verdicts)
    alive_now = counts["alive"]
    print(f"  stun: 探测 {len(targets)} 域名 → {counts}")

    # 仪器判决第二道:比例线。哨兵活着但活数对上轮腰斩,也当仪器/网络异常处理。
    prev_alive = (prev_state.get("lastRun") or {}).get("alive")
    floor = max(STUN_ALIVE_FLOOR,
                math.ceil(prev_alive * 0.5) if isinstance(prev_alive, int) else 0)
    if alive_now < floor:
        print(
            f"::error::本轮活数 {alive_now} 低于下限 {floor}"
            f"(绝对下限 {STUN_ALIVE_FLOOR};上轮 {prev_alive})⇒ 大面积异常,"
            "宁可判仪器故障也不批量剔除 —— 错删活服务器 = 泄漏窗口重开,本轮不采信。",
            file=sys.stderr)
        raise SystemExit(1)

    # 记忆更新:活者记今天,其余沿用;从未活过的不记。GC 随构造完成(不在全集就不会被写)。
    hosts_state = {}
    for h in targets:
        if verdicts.get(h) == "alive":
            hosts_state[h] = {"lastAliveAt": NOW, "ports": sorted(targets[h])}
        else:
            prev = prev_hosts.get(h)
            if prev and parse_stamp(prev.get("lastAliveAt")):
                hosts_state[h] = {"lastAliveAt": prev["lastAliveAt"],
                                  "ports": sorted(targets[h])}

    cutoff = parse_stamp(NOW) - timedelta(days=STUN_MEMORY_DAYS)
    members = {h for h, e in hosts_state.items()
               if parse_stamp(e["lastAliveAt"]) >= cutoff}

    assert_stun_members_recently_alive(members, hosts_state, cutoff)
    assert_stun_membership_bounded(members, candidates, prev_members)

    joined = sorted(members - prev_members)
    left = sorted(prev_members - members)
    if joined or left:
        print(f"  stun: 新入 {len(joined)} · 移除 {len(left)}"
              + (f" · 移除的是 {', '.join(left[:5])}{'…' if len(left) > 5 else ''}" if left else ""))

    result = write_list(
        STUN_LIST, "公开 STUN 服务器域名",
        "候选名单:pradt2/always-online-stun(MIT);收录判据:本仓 CI 每日发真实 "
        f"STUN Binding Request 验活,只收 {STUN_MEMORY_DAYS} 天内有响应的(scripts/stun_check.py)",
        [f"DOMAIN,{h}" for h in sorted(members)],
    )
    save_stun_state(hosts_state, probed=len(targets), alive=alive_now)
    return result


# ---------------------------------------------------------------- 一手来源:厂商官方端点

def fetch_json(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "minerva-rulesets-builder"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def build_microsoft365():
    """
    Microsoft 365 的服务域名,来自**微软自己发布的端点服务**(一手,不是谁的策展)。

    通配符形态实测(2026-08-07:190 个模式):
      `*.aadrm.com`        70 个 → `DOMAIN-SUFFIX,aadrm.com`(前导通配 = 后缀匹配)
      `outlook.office.com` 118 个 → `DOMAIN,outlook.office.com`
      🔴 `*cdn.onenote.net` / `autodiscover.*.onmicrosoft.com` 2 个 → **Surge 表达不了**

    🔴 **表达不了的那几个要打印出来,不许静默丢。** 砍掉覆盖面却不吭声,
    读起来就像「全覆盖」—— 本项目对「东西在但不起作用」这类静默失真是零容忍的。

    v1 只做域名。那 93 个 IP 段留给以后(summary 里已写明这份是域名层),
    混进同一份清单会让「这是什么」这个问题有两个答案。
    """
    groups = fetch_json(O365_URL)
    suffixes, exacts, skipped = set(), set(), []
    for g in groups:
        for pattern in g.get("urls", []):
            p = pattern.strip().lower()
            if not p:
                continue
            if p.startswith("*.") and "*" not in p[2:]:
                suffixes.add(p[2:])
            elif "*" not in p:
                exacts.add(p)
            else:
                skipped.append(p)

    if skipped:
        # 去重后打印:让「少了几个」这件事在日志里看得见。
        for p in sorted(set(skipped)):
            print(f"  ⚠️ microsoft-365: 跳过 {p!r} —— 通配符不在开头,Surge 表达不了",
                  file=sys.stderr)

    # 已被某个后缀覆盖的精确域名就不再单列 —— 同一件事写两遍是噪音,不是更安全。
    exacts = {d for d in exacts
              if not any(d == s or d.endswith("." + s) for s in suffixes)}
    lines = ([f"DOMAIN-SUFFIX,{d}" for d in sorted(suffixes)]
             + [f"DOMAIN,{d}" for d in sorted(exacts)])
    return write_list(
        "sets/microsoft/microsoft-365.list", "Microsoft 365 服务域名",
        "Microsoft 365 官方端点服务 endpoints.office.com(厂商一手数据)", lines)


def build_github():
    """
    GitHub 自家服务的 IP 段,来自 **GitHub 官方 `api.github.com/meta`**(一手)。

    取哪几个键见 `GITHUB_META_KEYS` 的注释 —— **那是一次取舍,summary 里说清楚了**。
    ⚠️ 这份**只有 IP 段没有域名**:GitHub 官方没发布域名清单,我们不替它编一个。
    """
    meta = fetch_json(GITHUB_META_URL)
    v4, v6 = set(), set()
    for key in GITHUB_META_KEYS:
        for cidr in meta.get(key, []):
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                print(f"  ⚠️ github: 读不懂的网段 {cidr!r},跳过", file=sys.stderr)
                continue
            (v4 if net.version == 4 else v6).add(net)

    lines = ([f"IP-CIDR,{n},no-resolve"
              for n in sorted(v4, key=lambda n: int(n.network_address))]
             + [f"IP-CIDR6,{n},no-resolve"
                for n in sorted(v6, key=lambda n: int(n.network_address))])
    return write_list(
        "sets/dev/github.list", "GitHub 服务 IP 段",
        f"GitHub 官方 api.github.com/meta 的 {'/'.join(GITHUB_META_KEYS)} 段(厂商一手数据)",
        lines)


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


def assert_known_times_never_become_unknown(old_entries, entries):
    """
    🔴 机器判据:**已经知道的时间,不许退回「不知道」。**

    「这份东西上次变化于 X」一旦知道了就永远知道 —— 内容再怎么变也只会让 X 前移,
    不可能让我们**忘掉**它。所以这个方向的变化只能是 bug。

    真事(2026-08-07 加这条判据的原因):自建层加进「本轮重写过就用 NOW」之后,
    出现了这条路径 —— 文件在上一轮被重写(记了 NOW)、那一轮却没提交成,
    下一轮就成了「没重写 + git 里查无此文件」⇒ **时间凭空消失,而内容一个字节没变**。
    上面那条 `assert_unchanged_content_keeps_its_time` 抓不到它:那条只管有指纹的索引层。
    """
    lost = [(e["path"], old_entries[e["path"]]["updatedAt"])
            for e in entries
            if old_entries.get(e["path"], {}).get("updatedAt") and not e.get("updatedAt")]
    if not lost:
        return
    print(
        "::error::下列条目**丢了已知的更新时间**(退回「不知道」)—— 日期只会前移,不会被忘掉,"
        "这个方向只能是 bug:\n  " + "\n  ".join(f"{p}: 原本 {t!r},现在没有了" for p, t in lost),
        file=sys.stderr,
    )
    raise SystemExit(1)


def build_manifest(generated_counts, indexed_entries, old, rewritten):
    print("[3/3] 生成 manifest.json…")
    times = git_last_commit_times()
    old_entries = entries_by_path(old)
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
            #
            # 🔴 第三档**沿用上一版**,少了它会真掉数据:文件在上一轮被重写(记了 NOW)、
            #    但那一轮**没提交成**,下一轮就变成「没重写 + git 里查无此文件」⇒ 时间凭空消失。
            #    **内容一个字节没变,已知的日期却退回「不知道」** —— 和索引层「这轮没拉到就沿用上次」
            #    是同一条纪律。下面 `assert_known_times_never_become_unknown` 守着它。
            stamp = (NOW if rel in rewritten
                     else times.get(rel) or old_entries.get(rel, {}).get("updatedAt"))
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

    assert_unchanged_content_keeps_its_time(old_entries, entries)
    assert_known_times_never_become_unknown(old_entries, entries)

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
    counts, rewritten = build_sets(old)
    indexed_entries = build_indexed(entries_by_path(old))
    build_manifest(counts, indexed_entries, old, rewritten)
    print("完成。")


if __name__ == "__main__":
    main()
