# 来源与署名

本仓分三层,**三层的责任完全不同**,请分开看待。

| 层 | 内容在哪 | 我们能说什么 |
|---|---|---|
| `authored` | 在本仓 | 从一手来源生成,来源与脚本都公开可查 |
| `mirrored` | 在本仓 | **内容是别人的**,我们在许可范围内托管了一份并如实署名 |
| `indexed` | 不在本仓 | 我们选了它,**但没有审核它的内容** |

---

## 自建层(`sets/`)—— 内容在本仓,我们对它负责

| 清单 | 一手来源 | 许可 | 说明 |
|---|---|---|---|
| `sets/region/cn-ipv4.list`<br>`sets/region/cn-ipv6.list`<br>`sets/region/cn-asn.list` | [APNIC `delegated-apnic-latest`](https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest) | 公开注册数据 | 由 `scripts/build.py` 从注册机构每日发布的分配记录直接推导。**不涉及任何人对「哪些值得收进来」的编辑判断**,因此也没有别人的策展可以侵犯。 |
| `sets/microsoft/microsoft-365.list` | [Microsoft 365 官方端点服务](https://endpoints.office.com/endpoints/worldwide?clientrequestid=b10c5ed1-bad1-445f-b386-b919946339a7)([微软文档](https://learn.microsoft.com/microsoft-365/enterprise/microsoft-365-endpoints)) | 厂商自己公布的服务数据 | 每天自动跟随。**只取域名**;微软同时公布的 IP 段暂未收录。⚠️ 有两个模式(`*cdn.onenote.net`、`autodiscover.*.onmicrosoft.com`)通配符在中间,**Surge 表达不了,已排除**——构建日志里看得见,不是悄悄丢的。 |
| `sets/dev/github.list` | [GitHub 官方 `api.github.com/meta`](https://docs.github.com/rest/meta/meta) | 厂商自己公布的服务数据 | 每天自动跟随。**只有 IP 段没有域名**——官方没发布域名清单,我们不替它编。⚠️ **只取 `web`/`api`/`git`/`packages`/`pages`**;`actions` 一个键就 7000+ 条**且是 Azure 的地址段**(Codespaces/Copilot 同理),那是别人家的云,不是 GitHub 自己的服务端点。 |

> 🔴 **厂商官方端点算不算「一手」?算。** 判据和 APNIC 那三条一样:内容来自**权威本身**
> (地址的分配者 / 服务的运营者),不是第三方对「哪些值得收」的编辑判断。
> 对照 `sets/network/stun.list` 之所以只能标 `mirrored`,正是因为那份的取舍是 pradt2 做的。

> APNIC 的 delegated 文件记录的是「这段地址 / 这个 ASN 分配给了哪个经济体的组织」这一注册事实。
> ⚠️ 文件第五列**三种类型三种含义**:`ipv4` 是地址**数量**(要自己切成 CIDR)、`ipv6` **直接是前缀长度**、
> `asn` 是连续个数。数行数 ≠ 数条目。

---

## 镜像层(`sets/network/stun.list`)—— 内容在本仓,但**内容是别人的**

| 清单 | 上游 | 许可证 | 我们做了什么 |
|---|---|---|---|
| `sets/network/stun.list`(621 条) | [pradt2/always-online-stun](https://github.com/pradt2/always-online-stun) 的 `candidates.txt` | MIT(明许再分发) | 只做了**机械变换**:剥掉端口、去掉裸 IP、去重排序,产出 `DOMAIN,` 规则行 |

> 🔴 **它为什么不标 `authored`。** 内容 100% 来自上游,我们**没有加入任何属于自己的判断** ——
> 收哪些、不收哪些,全是他们的工作。标成「我们写的」就是假背书。
> 上游是 `host:port` 格式,Surge 的 `DOMAIN-SET` 消费不了,所以这一份只能托管、不能索引。
>
> **它什么时候能升 `authored`:** 等本仓有了自己的收录判据 —— 自己验活、自己从厂商文档补充、
> 自己剔除死条目。**标签跟着现实走,不跟着愿望走。**

---

## 索引层 —— 内容**不在本仓**,我们只记录地址

**我们选了它们,但没有审核它们的内容。** 下面每一条,你引用的都是上游自己的服务器,
拿到的永远是上游的最新版本;本仓一个字节都没有复制。

| 清单 | 上游 | 许可证 | 指令 |
|---|---|---|---|
| 广告与追踪域名 | [privacy-protection-tools/anti-AD](https://github.com/privacy-protection-tools/anti-AD) | MIT | `RULE-SET` |
| 秋风广告规则 | [TG-Twilight/AWAvenue-Ads-Rule](https://github.com/TG-Twilight/AWAvenue-Ads-Rule) | GPL-3.0 | `RULE-SET` |
| 广告与追踪 / Apple / iCloud / Google / Telegram IP 段 /<br>受限域名 / 非中国 TLD / 局域网设备 | [Loyalsoldier/surge-rules](https://github.com/Loyalsoldier/surge-rules) | GPL-3.0 | 除 Telegram IP 段是 `RULE-SET` 外,其余均为 `DOMAIN-SET` |

完整逐条信息(条数、上次更新、分类、说明)在 `manifest.json`;策展表在 `indexed/sources.json`。

### 收录标准(`indexed/sources.json` 里也写着,那份是执行时的正本)

1. 🔴 **来源必须说得清。** 上游要么自己就是一手来源,要么**逐条写明它的数据来自哪里**。
   判据**不是**「有没有上游」,而是「**我们能不能如实告诉使用者这些内容是谁的**」——
   说不清出处,我们标上去的许可证与署名就是假的,和「蓝勾不许假背书」是同一条纪律。
   > **这一条 2026-08-07 改过口,原文是「不收聚合站 / 二手转载」。** 改的原因是它和现实对不上:
   > 本仓收的 Loyalsoldier 那 9 条**本身就是下游**(它 README 明写数据来自 v2fly/domain-list-community、
   > felixonmars、17mon)——**按原文字面执行,那 9 条当初就不该收**。
   > 而真正让它站得住的,是它**把来源逐条写清楚了**;真正让 ACL4SSR 站不住的,是它一个字都没写。
   > 判据得描述我们实际在做的事,否则下次策展只能靠翻例外表。
2. **只收没有使用限制声明的上游。** README 里写着禁止转载 / 禁止发布的一律不收——
   **维护者写下的话压过仓库上那个许可证徽章**,两者冲突时以前者为准。
3. **只收 Surge 能直接消费的格式**,并逐条声明 `directive`。为了收录而做格式转换 =
   托管派生内容 = 我们刚刚才通过「只索引不托管」消掉的授权风险又回来了。
4. 🔴 **不收文件名编码了路由决定的清单**(`proxy.txt` / `direct.txt` 这类)。理由见 README 第一原则。
   同一个上游里,描述性的收、决定性的不收——这是本仓策展工作的主要内容。
5. 每条都要有一句人话说明。**我们策展的是目录,不是内容。**

### 被评估过但没有收录的

| 上游 | 没收的原因 |
|---|---|
| `hagezi/dns-blocklists` | 产出是 Adblock Plus 语法或**不带前导点**的裸域名。后者在 `DOMAIN-SET` 里只做**精确匹配**,而去广告需要匹配子域——语义对不上,收进来会给人一份看起来很大、实际漏得厉害的清单。 |
| `felixonmars/dnsmasq-china-list` | dnsmasq 格式(`server=/example.com/114.114.114.114`),Surge 无法直接消费。转换即托管派生内容,见标准 3。 |
| `blackmatrix7/ios_rule_script` | README 明示禁止任何形式的转载与发布,见标准 2。 |
| `Repcz/Tool` | 两条:①是聚合站,多份清单转自他人,我们标注的许可证对不上真实来源(标准 1)②README 明示「禁止任何形式的转载或发布至国内平台」(标准 2)。 |
| `MetaCubeX/meta-rules-dat` | 格式不对(标准 3)。它的 `geo/geosite/*.list` 是 **Clash 的 `+.domain` 语法**(如 `+.fast.com`),Surge 的 `DOMAIN-SET` 不认这个前缀——会把整行当成一个**名叫 `+.fast.com` 的字面域名**,于是**一条都匹配不上、而且不报错**。要收就得逐行改写,那就是托管派生内容。 |
| `ACL4SSR/ACL4SSR` | 说不清来源(标准 1)。它有 158 个实体名清单、格式也是 Surge 直吃的,**唯独没有任何来源署名**——文件头只有「内容:Netflix / 数量:41条」。我们无法如实告诉使用者这些内容是谁的,标上「ACL4SSR · CC-BY-SA-4.0」就是又一次假归因。**这一条只要上游补上署名就可以重新评估。** |

> 🔴 **为什么「流媒体」这一类目前是空的。** 生态里这一类的主要供给就是上面这几家:
> blackmatrix7(禁转载)· MetaCubeX(格式不对)· ACL4SSR(说不清来源),而 Loyalsoldier 不做这一类。
> **不是漏了,是暂时没有一个过得了闸门的来源。** 它要么等某个上游补齐署名,
> 要么走自建层——而流媒体厂商基本不公布自己的域名清单,自建也缺一手依据。
> 在有真来源之前,这一格宁可空着:填一份来路不明的进去,比空着更糟。

---

## 如果你是上游维护者

如果你希望本仓移除对你项目的索引,开一个 issue 即可,我们会照办——索引层本来就只是一行地址。
