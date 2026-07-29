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

1. **只收上游自己策展的清单**,不收聚合站 / 二手转载——我们标注的许可证必须对得上真实的内容来源。
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

---

## 如果你是上游维护者

如果你希望本仓移除对你项目的索引,开一个 issue 即可,我们会照办——索引层本来就只是一行地址。
