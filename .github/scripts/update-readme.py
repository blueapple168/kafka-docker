# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Update the published-image table in README.md.

The table lives between the markers below and is fully generated; the rest of
the README is hand written and never touched by this script.

    <!-- IMAGE-TAGS:BEGIN -->
    | 镜像 tag | 变体 | ... |
    <!-- IMAGE-TAGS:END -->

Design notes:
  * Pure standard library, no network access: the caller (workflow or human)
    passes the image metadata in as JSON.
  * Idempotent: when the rendered table equals the existing one the file is
    left untouched, so no empty commit is produced.
  * Deterministic ordering: newest ``built_at`` first, ties broken by tag, so
    repeated runs with the same input always render the same bytes.
"""

import argparse
import json
import re
import sys
from pathlib import Path

BEGIN_MARKER = "<!-- IMAGE-TAGS:BEGIN -->"
END_MARKER = "<!-- IMAGE-TAGS:END -->"

HEADER = [
    "镜像 tag",
    "变体",
    "Kafka 版本",
    "平台",
    "Digest（前 16 位）",
    "构建完成（UTC）",
]
COLUMN_COUNT = len(HEADER)

DIGEST_PREFIX_LEN = 16
TAG_SUFFIXES = ("-native-uos", "-uos")


class UpdateError(Exception):
    """Raised when the README structure or the input data is unusable."""


def kafka_version_from_tag(tag):
    """Derive the Kafka version from an image tag, e.g. 4.3.1-native-uos -> 4.3.1."""
    for suffix in TAG_SUFFIXES:
        if tag.endswith(suffix):
            return tag[: -len(suffix)]
    return tag


def normalize_digest(digest):
    """Keep only the first 16 hex characters of the sha256 digest."""
    value = (digest or "").strip()
    if value.startswith("sha256:"):
        value = value[len("sha256:"):]
    return "`sha256:{}`".format(value[:DIGEST_PREFIX_LEN]) if value else ""


def split_row(line):
    """Split a markdown table row into stripped cells."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = stripped.strip("|").split("|")
    return [cell.strip() for cell in cells]


def parse_existing_rows(block_lines):
    """Parse the rows already present between the markers."""
    rows = []
    for line in block_lines:
        cells = split_row(line)
        if cells is None or len(cells) != COLUMN_COUNT:
            continue
        # Skip the header row and the |---| separator row.
        if cells[0] == HEADER[0]:
            continue
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue
        tag = cells[0].strip("`").strip()
        if not tag:
            continue
        rows.append(
            {
                "tag": tag,
                "variant": cells[1],
                "version": cells[2],
                "platforms": cells[3],
                "digest": cells[4],
                "built_at": cells[5],
            }
        )
    return rows


def normalize_incoming_rows(data):
    """Validate and normalize the rows supplied by the caller."""
    raw_rows = data.get("rows")
    if not isinstance(raw_rows, list):
        raise UpdateError("输入 JSON 缺少 rows 数组")
    rows = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise UpdateError("rows 中的元素必须是对象: {!r}".format(raw))
        tag = str(raw.get("tag") or "").strip()
        if not tag:
            raise UpdateError("rows 中存在缺少 tag 的记录: {!r}".format(raw))
        variant = str(raw.get("variant") or "").strip()
        if variant not in ("jvm", "native"):
            raise UpdateError("变体必须是 jvm 或 native, 实际为 {!r}".format(variant))
        rows.append(
            {
                "tag": tag,
                "variant": variant,
                "version": str(raw.get("version") or kafka_version_from_tag(tag)).strip(),
                "platforms": str(raw.get("platforms") or "").strip() or "linux/amd64, linux/arm64",
                "digest": normalize_digest(raw.get("digest")),
                "built_at": str(raw.get("built_at") or "").strip(),
            }
        )
    return rows


def merge_rows(existing, incoming, max_rows):
    """Merge by tag (incoming wins) and keep the newest ``max_rows`` entries."""
    merged = {row["tag"]: row for row in existing}
    for row in incoming:
        merged[row["tag"]] = row
    # 先按 tag 升序排好, 再按 built_at 降序稳定排序: 同一批次构建的多个变体
    # (时间戳相同) 因此保持固定的 tag 字典序, 渲染结果可重复。
    ordered = sorted(merged.values(), key=lambda r: r["tag"])
    ordered.sort(key=lambda r: r["built_at"], reverse=True)
    return ordered[:max_rows]


def render_table(rows):
    """Render the markdown table for the given rows."""
    lines = [
        "| " + " | ".join(HEADER) + " |",
        "| " + " | ".join(["---"] * COLUMN_COUNT) + " |",
    ]
    for row in rows:
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                row["tag"],
                row["variant"],
                row["version"],
                row["platforms"],
                row["digest"],
                row["built_at"],
            )
        )
    return lines


def locate_block(lines):
    """Return (begin_index, end_index) of the markers, both inclusive."""
    begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN_MARKER]
    ends = [i for i, line in enumerate(lines) if line.strip() == END_MARKER]
    if not begins:
        raise UpdateError("README 中找不到标记 {}".format(BEGIN_MARKER))
    if len(begins) > 1 or len(ends) > 1:
        raise UpdateError(
            "README 中标记重复出现 (BEGIN {} 处, END {} 处), 无法确定要更新的区块".format(
                len(begins), len(ends)
            )
        )
    if not ends:
        raise UpdateError("README 中找不到标记 {}".format(END_MARKER))
    if ends[0] < begins[0]:
        raise UpdateError("README 中标记顺序颠倒: END 出现在 BEGIN 之前")
    return begins[0], ends[0]


def update_readme(readme_path, data_path, max_rows, check_only):
    readme = Path(readme_path)
    if not readme.is_file():
        raise UpdateError("README 不存在: {}".format(readme))

    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    incoming = normalize_incoming_rows(data)

    original = readme.read_text(encoding="utf-8")
    lines = original.splitlines()
    begin, end = locate_block(lines)

    existing = parse_existing_rows(lines[begin + 1:end])
    merged = merge_rows(existing, incoming, max_rows)
    table = render_table(merged)

    updated_lines = lines[: begin + 1] + table + lines[end:]
    updated = "\n".join(updated_lines)
    if original.endswith("\n"):
        updated += "\n"

    changed = updated != original
    if check_only:
        return changed
    if changed:
        readme.write_text(updated, encoding="utf-8", newline="\n")
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description="更新 README.md 中的已发布镜像清单")
    parser.add_argument("--readme", default="README.md", help="README 路径, 默认 README.md")
    parser.add_argument("--data", required=True, help="镜像元数据 JSON 文件路径")
    parser.add_argument("--max-rows", type=int, default=12, help="清单最多保留的行数, 默认 12")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验不写入; 若 README 需要变更则以退出码 1 结束",
    )
    args = parser.parse_args(argv)

    try:
        changed = update_readme(args.readme, args.data, args.max_rows, args.check)
    except (UpdateError, json.JSONDecodeError, OSError) as e:
        print("error: {}".format(e), file=sys.stderr)
        return 2

    if args.check:
        if changed:
            print("README 需要更新（当前内容与给定镜像元数据不一致）")
            return 1
        print("README 已是最新")
        return 0

    print("README 已更新" if changed else "README 无变化，未写入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
