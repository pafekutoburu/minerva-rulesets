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
| `sets/network/stun.list` | **本仓 CI 自己的实测**;候选名单来自 [pradt2/always-online-stun](https://github.com/pradt2/always-online-stun) 的 `candidates.txt`(MIT,如实署名) | 实测结果;候选名单 MIT | CI 每天向每台候选与在册服务器发**真实 STUN Binding Request**(`scripts/stun_check.py`),只收 **7 天内有响应**的;连续 7 天无响应才移除。上游把还活着的服务器从候选池剔掉时,我们**不跟着剔**——成员退出的唯一途径是我们自己的实测。死掉的 STUN 服务器不会泄漏任何人的 IP,所以移除无安全代价;哪天它复活,次日就回清单。**2026-08-07 从 `mirrored` 升级**(升级前它只是候选池的机械变换)。 |

> 🔴 **厂商官方端点算不算「一手」?算。** 判据和 APNIC 那三条一样:内容来自**权威本身**
> (地址的分配者 / 服务的运营者),不是第三方对「哪些值得收」的编辑判断。
> `sets/network/stun.list` 的「一手」则是**本仓自己的实测**:候选线索来自 pradt2,
> 但每一条能不能进清单,由我们每天发的真实 STUN 请求裁决 ——
> 它曾因「取舍全是 pradt2 做的」只配标 `mirrored`(2026-07-29 至 2026-08-07),验活判据建成后才升级。

> APNIC 的 delegated 文件记录的是「这段地址 / 这个 ASN 分配给了哪个经济体的组织」这一注册事实。
> ⚠️ 文件第五列**三种类型三种含义**:`ipv4` 是地址**数量**(要自己切成 CIDR)、`ipv6` **直接是前缀长度**、
> `asn` 是连续个数。数行数 ≠ 数条目。

---

## 镜像层(`sets/`)—— 内容是别人的,我们在许可范围内托管了一份并如实署名

| 清单 | 上游 | 许可 | 说明 |
|---|---|---|---|
| `sets/game/games-non-cn.list`(`category-games-!cn`)<br>`sets/game/games-cn.list`(`category-games-cn`)<br>`sets/finance/banks-cn.list`(`category-bank-cn`)<br>`sets/finance/securities-cn.list`(`category-securities-cn`)<br>`sets/finance/finance-global.list`(`category-finance`)<br>`sets/crypto/cryptocurrency.list`(`category-cryptocurrency`)<br>`sets/shopping/ecommerce-global.list`(`category-ecommerce`)<br>`sets/shopping/jd.list`(`jd`)<br>`sets/shopping/pinduoduo.list`(`pinduoduo`)<br>`sets/shopping/alibaba.list`(`alibaba`) | [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) 的官方发布物 [`dlc.dat_plain.yml`](https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat_plain.yml) | MIT | 2026-09-15 起。官方生成器自己展开好的明文(`include:` 已递归、`@-attr` 已按官方语义过滤),`scripts/build.py` 只做「一行换一种写法」:`domain:`→`DOMAIN-SUFFIX`、`full:`→`DOMAIN`、`keyword:`→`DOMAIN-KEYWORD`;`regexp:` Surge 表达不了,略去并写进表头;`@cn` / `@ads` 等属性一律去掉、取整份清单。**一条不增、一条不删** —— 「收哪些、不收哪些」全是 v2fly 社区的判断,所以只配标镜像。写入前四道保险:发布物残缺 / 清单改名 / 自称条数与解析不符 / 比上一版腰斩,任一红整轮退出。 |

> **为什么不经转换器、直接读官方发布物**:见下面索引层「dlc→Surge 转换器对决记录」——
> 生态里所有转换器都在排除式包含语法上漏条,而官方明文导出没有这个问题。

> **这一层的升级史**:2026-09-15 之前唯一的成员是 `sets/network/stun.list`(2026-07-29 收录):当时它的内容 100%
> 照抄上游候选池,「收哪些、不收哪些」全是 pradt2 的工作,标 `authored` 就是假背书。
> **2026-08-07 起它的收录判据自建**(CI 每日验活,见上面自建层表),这才升了级 ——
> 当初写下的升级条件(「自己验活、自己剔除死条目」)如今兑现,**标签跟着现实走,不跟着愿望走**。
> 层级本身保留:将来再有「内容是别人的、我们在许可范围内托管一份」的清单,仍走这一层、如实署名。

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
| `HotKids/Rules` | README 首句「自用规则」、**未声明许可证**;`Surge/RULE-SET/Finance.list` 只有 22 条、全是美国银行(American Express / Chase …),挂「金融」会误导。无来源声明(维护者手写)。2026-09-15 评估。 |
| `dler-io/Rules` | README **零来源声明、零署名**、未声明许可证(标准 1,与 ACL4SSR 同病)。2026-09-15 评估。 |
| `DustinWin/ruleset_geodata` | 两条:①产物是 mihomo 的 `+.domain` 语法(`games.list` 899 行里 837 行带 `+.`),Surge 当字面域名(标准 3,与 MetaCubeX 同病);②README 自述 `games` / `games-cn` 源里**混入了 blackmatrix7**(禁转载源)。2026-09-15 评估。 |
| `GeQ1an/Rules` · `LM-Firefly/Rules` | 四类相关文件只有 Quantumult X / Clash YAML 格式(标准 3);LM-Firefly 自述「自用备份」、内容转自他人(标准 1)。2026-09-15 评估。 |
| `ImpXada/Geosite2Surge`(dlc→Surge 转换器) | **不展开 `include:`**:`category-games` 产物 770 条,官方 `dlc.dat` 1140 条,产物里还留着 `#include:` 注释。未声明许可证。2026-09-15 实测。 |
| `alecthw/geosite-surge`(dlc→Surge 转换器) | 产物里**多出 dlc 根本没有的条目**(`category-games` 多 10 条 `epicgames-download*.akamaized.net`),来源不纯;另有 `@-attr` 缺条(见下面对决记录)。未声明许可证。2026-09-15 实测。 |
| `fqx/surge-domain-set-from-v2fly`(dlc→Surge 转换器,MIT) | 丢 IDN 域名与部分纯 ASCII 条目(`category-finance` 缺 91,含 `114bank.co.jp`),原因不明;另有 `@-attr` 缺条。2026-09-15 实测。 |
| `lhie1/Rules` · `DivineEngine/Profiles` · `ConnersHua/Profiles` | 已死:GitHub TOS 封禁 / 404 / 404(2026-09-15 查)。记一笔免得再找。 |

> 🔴 **为什么「流媒体」这一类目前是空的。** 生态里这一类的主要供给就是上面这几家:
> blackmatrix7(禁转载)· MetaCubeX(格式不对)· ACL4SSR(说不清来源),而 Loyalsoldier 不做这一类。
> **不是漏了,是暂时没有一个过得了闸门的来源。** 它要么等某个上游补齐署名,
> 要么走自建层——而流媒体厂商基本不公布自己的域名清单,自建也缺一手依据。
> 在有真来源之前,这一格宁可空着:填一份来路不明的进去,比空着更糟。

> 🔴 **为什么「政务与公共服务」这一类目前是空的(2026-09-15 普查)。** 生态里唯一说得清来源的政府类清单是
> v2fly 社区库的 `category-gov-ir`(伊朗)与 `category-gov-ru`(俄罗斯),**没有**中国大陆、美国或全球政府类;
> 单独摆两份地区性清单比空着更怪。中国大陆的 `.gov.cn` 后缀本身就是事实,一行 `DOMAIN-SUFFIX,gov.cn` 顶一份清单,
> 不值得做成规则集。美国 `.gov` 有注册机构官方全量清单,记在下面「自建层候选线索」里。

### dlc→Surge 转换器对决记录(2026-09-15)

v2fly/domain-list-community(下称 dlc,MIT)是四类描述性清单的事实来源,但它的私有语法 Surge 吃不了,
只能经第三方转换器。**转换器的产物忠不忠实,不能靠星数猜,要拿真值比**:
① 真值 = 官方 `dlc.dat`(release 附件,标准库 protobuf 解码);② 交叉 = 按官方 `main.go` 语义写的文本展开器
(`include:` 递归、`@attr` / `@-attr` 过滤、`&` 关联);两者对 13 个清单逐条一致。
结果:`category-finance` / `-cryptocurrency` / `-ecommerce` / `-securities-cn` / `-games-!cn` / `-game-platforms-download` /
`jd` / `pinduoduo` / `alibaba` 在 AkinoKaede/domain-list-community-converter 的产物中**逐条精确**;
但 **`category-bank-cn`(官方 135 条 → 产物 55 条)、`category-games-cn`(283 → 264)、`category-games`(1140 → 1126)**
在三家转换器里**同样缺条**——根因是 dlc 较新的 `include:xxx @-attr`(排除式包含)语法三家解析器都不认识,
含它的 `include` 被整段丢弃(工行主域名 `95588.com`、库洛游戏 `kurobbs.com` 就是这么没的)。
全库 1539 个文件只有 7 个用了这个语法,偏偏砸中这两份。**凡是从 dlc 转来的清单,收录前都要重跑这一步。**

---

## 自建层候选线索(登记未做,2026-09-15 普查顺带记下)

厂商 / 注册机构自己公布的数据,判据与 APNIC、微软那几条相同,**做之前先答「对别国用户也成立吗」**。

| 分类 | 线索 | 机器可读? | 备注 |
|---|---|---|---|
| gov | [cisagov/dotgov-data](https://github.com/cisagov/dotgov-data)(CC0,美国 `.gov` 注册机构官方全量清单,CSV) | ✅ | 与 APNIC 同类的注册事实,能走自建层 |
| game | Steam `api.steampowered.com/ISteamDirectory/GetCMList`;Xbox / PlayStation / Nintendo / Epic / Riot / Blizzard 的网络需求支持页 | Steam ✅,其余是人读文档 | 与 OpenAI / Anthropic 同档:手工维护 |
| finance | Stripe 官方 IP 段 JSON(`stripe.com/files/ips/`) | ✅ | 支付处理商基础设施,对个人用户价值存疑 |
| shopping | 无。Amazon 只公布 AWS 云段,那是云不是电商 | — | 记「没有一手来源」 |

---

## 如果你是上游维护者

如果你希望本仓移除对你项目的索引,开一个 issue 即可,我们会照办——索引层本来就只是一行地址。
