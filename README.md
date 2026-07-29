# minerva-rulesets

给 Surge 用的规则集目录。**任何 Surge 用户都能直接引用,不需要装 Minerva。**

---

## 第一原则:清单只回答「这是什么」,不回答「它该走哪」

生态里到处是这样的路径:

```
rules/Proxy/Netflix.list
```

它看起来只是个分类,其实**把「Netflix 走代理」这个决定焊进了资产本身**。那是某一个人的选择——
一个住在美国的用户要 Netflix 直连,同一份文件对他从根上就是错的。

所以本仓的路径里**永远不出现策略名**:

```
sets/region/cn-asn.list      ✅  它说的是「这些 ASN 属于中国大陆」——对所有人都一样的事实
sets/Proxy/Netflix.list      ❌  它说的是「Netflix 该走代理」——那是你的决定,不是事实
```

**「走哪」由你在自己的配置里写。** 这条纪律不是口号,`.github/workflows/` 里有一步机器判据在守:
路径里一旦出现策略名,CI 立刻变红。

---

## 两层,信任级别不同,请分开看待

| 层 | 内容在哪 | 我们能担保什么 |
|---|---|---|
| **自建(authored)** | **在本仓** | 从一手来源生成,来源与生成脚本都公开可查 |
| **镜像(mirrored)** | **在本仓** | **内容是别人的**,我们在其许可范围内托管了一份并如实署名 |
| **索引(indexed)** | **不在本仓**,指向上游 | **我们选了它,但没有审核它的内容。** 许可证与出处逐条标注 |

索引层**只记录地址,不复制任何内容**。这既是尊重上游的许可证,也意味着你拿到的永远是上游的最新版本。

镜像层只有在**上游许可证明许再分发、而它的原始格式 Surge 又消费不了**时才会出现——目前只有一条
(STUN 服务器域名)。它**不会**被伪装成自建:`manifest.json` 里 `layer` 与 `upstream` 两个字段
都会如实说明。逐条署名见 [`SOURCES.md`](SOURCES.md)。

---

## 怎么用

Surge 引用远程清单有**两条不同的指令**,取决于文件里每行长什么样:

```ini
# RULE-SET —— 文件里每行是完整规则(DOMAIN-SUFFIX,example.com)
RULE-SET,https://raw.githubusercontent.com/pafekutoburu/minerva-rulesets/refs/heads/main/sets/region/cn-asn.list,DIRECT

# DOMAIN-SET —— 文件里每行是裸域名(.example.com),前导点表示含子域
DOMAIN-SET,https://raw.githubusercontent.com/Loyalsoldier/surge-rules/release/icloud.txt,你的策略组名
```

> 🔴 **写错指令 Surge 不会报错,那份清单只是一条都匹配不上。**
> `manifest.json` 里每条都带 `directive` 字段,照着写即可。

最后那个参数是**你自己选的目标**——某个策略组的名字,或者 `DIRECT`。本仓不替你决定。

> ⚠️ 目标必须是你配置里**真实存在**的策略组名。写一个不存在的名字,Surge **不会报错也不会忽略**,
> 而是让匹配到的流量当场失败——面板上一切正常,现象只是「某些网站莫名其妙打不开」。

---

## 目录

`manifest.json` 是完整目录,机器可读,包含每条的分类、条数、上次更新时间、许可证与出处。

### 自建层

| 清单 | 内容 | 依据 |
|---|---|---|
| `sets/region/cn-ipv4.list` | 分配给中国大陆的 IPv4 网段 | APNIC 每日发布的注册数据 |
| `sets/region/cn-ipv6.list` | 分配给中国大陆的 IPv6 网段 | 同上 |
| `sets/region/cn-asn.list` | 分配给中国大陆的自治系统号 | 同上 |

> **别把它们说大:** Surge 内建的 `GEOIP,CN` 已经覆盖了大部分「境内直连」的需求。
> 这三份的价值在于**来源可查、可以只取 ASN 这一种粒度**,不是替代 `GEOIP,CN`。

### 镜像层

| 清单 | 内容 | 出处 |
|---|---|---|
| `sets/network/stun.list` | 公开 STUN 服务器域名(621 条) | [pradt2/always-online-stun](https://github.com/pradt2/always-online-stun),MIT |

> STUN 是设备用来发现自己公网 IP 的协议,浏览器里的 WebRTC 会用到它。
> 拦掉这些域名可以减少一类 IP 泄漏,代价是某些语音/视频通话可能受影响。

### 索引层

覆盖广告与追踪、Apple、Google、Telegram、地区判断、局域网设备等。完整清单见 `manifest.json`,
出处与许可证见 `SOURCES.md`。

---

## 自动更新

`.github/workflows/daily-refresh.yml` 每日 **02:00 UTC** 重建自建清单与 `manifest.json`,
也可以手动触发(`workflow_dispatch`)。

**内容没有变化时不会产生提交**——这样 `manifest.json` 里的 `updatedAt`(取自 git 最后提交时间)
才真正等于「这份内容上次变化的时间」,而不是「上次跑过任务的时间」。
一份半年没动过的清单就该显示成半年没动过。

---

## 许可证

本仓自己的内容(`sets/`、`scripts/`、`manifest.json`)采用 **MIT**,见 [`LICENSE`](LICENSE)。

索引层指向的第三方清单**不在本仓**,各自适用其上游许可证,逐条列在 `SOURCES.md`。
