"""build.py 纯函数的单元测试(标准库 unittest;CI 在生成之前先跑它)。
只测不碰网络的部分:发布物解析、写法转换、写入前的保险、以及「一张表定三件事」的一致性。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402

FIXTURE = '''lists:
  - name: "alpha"
    length: 4
    rules:
      - "domain:Example.com"
      - "full:api.example.com:@cn"
      - "regexp:^r+[0-9]+\\\\.example\\\\.com$:@cn"
      - "keyword:exam"
  - name: "beta"
    length: 1
    rules:
      - "domain:b.org:@ads:@cn"
'''


class DlcPlainParsing(unittest.TestCase):
    def test_parses_names_lengths_rules_and_attributes(self):
        lists = build.parse_dlc_plain(FIXTURE)
        self.assertEqual(set(lists), {"alpha", "beta"})
        self.assertEqual(lists["alpha"]["length"], 4)
        self.assertEqual(len(lists["alpha"]["rules"]), 4)
        self.assertEqual(lists["alpha"]["rules"][1], ("full", "api.example.com", ("cn",)))
        self.assertEqual(lists["beta"]["rules"][0], ("domain", "b.org", ("ads", "cn")))
        # regexp 里的 `\\.` 还原成 `\.`,不能再多也不能再少
        self.assertEqual(lists["alpha"]["rules"][2][1], r"^r+[0-9]+\.example\.com$")

    def test_conversion_maps_types_drops_regexp_and_sorts(self):
        lists = build.parse_dlc_plain(FIXTURE)
        lines, skipped = build.dlc_rules_to_surge(lists["alpha"]["rules"])
        self.assertEqual(lines, ["DOMAIN,api.example.com", "DOMAIN-KEYWORD,exam", "DOMAIN-SUFFIX,example.com"])
        self.assertEqual(skipped, 1)

    def test_attributes_are_dropped_not_filtered(self):
        lists = build.parse_dlc_plain(FIXTURE)
        lines, _ = build.dlc_rules_to_surge(lists["beta"]["rules"])
        self.assertEqual(lines, ["DOMAIN-SUFFIX,b.org"])


class DlcGuards(unittest.TestCase):
    def test_missing_list_is_red(self):
        with self.assertRaises(SystemExit):
            build.assert_dlc_list_sane("nope", None, [], None)

    def test_length_mismatch_is_red(self):
        item = {"length": 3, "rules": [("domain", "a.com", ())]}
        with self.assertRaises(SystemExit):
            build.assert_dlc_list_sane("x", item, ["DOMAIN-SUFFIX,a.com"], None)

    def test_empty_output_is_red(self):
        item = {"length": 1, "rules": [("regexp", "^a$", ())]}
        with self.assertRaises(SystemExit):
            build.assert_dlc_list_sane("x", item, [], None)

    def test_shrinking_by_half_is_red_but_small_drift_passes(self):
        item = {"length": 4, "rules": [("domain", f"{i}.com", ()) for i in range(4)]}
        lines = [f"DOMAIN-SUFFIX,{i}.com" for i in range(4)]
        with self.assertRaises(SystemExit):
            build.assert_dlc_list_sane("x", item, lines, prev_count=10)
        build.assert_dlc_list_sane("x", item, lines, prev_count=6)   # 4 ≥ 6 × 0.5,放行
        build.assert_dlc_list_sane("x", item, lines, prev_count=None)  # 第一轮没有上一版


class OneTableDrivesThreeThings(unittest.TestCase):
    def test_every_dlc_list_is_mirrored_with_upstream_and_summary(self):
        for rel in build.DLC_LISTS:
            self.assertIn(rel, build.MIRRORED_SETS, rel)
            self.assertEqual(build.MIRRORED_SETS[rel]["license"], "MIT")
            self.assertTrue(build.SET_SUMMARIES.get(rel), f"{rel} 缺人话说明")
            self.assertTrue(rel.startswith("sets/") and rel.endswith(".list"), rel)

    def test_paths_never_encode_a_routing_decision(self):
        for rel in build.DLC_LISTS:
            low = rel.lower()
            for bad in ("proxy", "direct", "reject", "代理", "直连"):
                self.assertNotIn(bad, low, rel)


if __name__ == "__main__":
    unittest.main()
