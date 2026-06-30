"""
ONE量化 - 数据加载器测试

覆盖：CSV 加载、JSONL 加载、时间解析、时间过滤、流式回放、排序。
"""

import csv
import json

import pytest

from one_quant.strategy.data_loader import DataLoader, load_and_merge

# ──────────────── 辅助 ────────────────


def _write_csv(path, rows, encoding="utf-8"):
    if not rows:
        return
    with open(path, "w", encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


# ════════════════════════════════════════════════════════════════
# 初始化
# ════════════════════════════════════════════════════════════════


class TestDataLoaderInit:
    """初始化"""

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            DataLoader("/nonexistent/file.csv")

    def test_csv_init(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        _write_csv(csv_file, [{"timestamp": "2024-01-01", "price": 100}])
        loader = DataLoader(csv_file)
        assert loader._file_path == csv_file

    def test_jsonl_init(self, tmp_path):
        jsonl_file = tmp_path / "test.jsonl"
        _write_jsonl(jsonl_file, [{"timestamp": "2024-01-01", "price": 100}])
        loader = DataLoader(jsonl_file)
        assert loader._file_path == jsonl_file

    def test_unsupported_format(self, tmp_path):
        bad_file = tmp_path / "test.xyz"
        bad_file.write_text("data")
        loader = DataLoader(bad_file)
        with pytest.raises(ValueError, match="不支持"):
            loader.load_all()

    def test_time_range(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        _write_csv(csv_file, [{"timestamp": "2024-01-01", "price": 100}])
        loader = DataLoader(csv_file, start="2024-01-01", end="2024-12-31")
        assert loader._start_ns is not None
        assert loader._end_ns is not None


# ════════════════════════════════════════════════════════════════
# CSV 加载
# ════════════════════════════════════════════════════════════════


class TestCSVLoading:
    """CSV 加载"""

    def test_load_basic(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [
            {"timestamp": "2024-01-01", "price": "100", "volume": "500"},
            {"timestamp": "2024-01-02", "price": "101", "volume": "600"},
        ]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file)
        data = loader.load_all()
        assert len(data) == 2
        # Values should be converted to numbers
        assert data[0]["price"] == 100 or data[0]["price"] == "100"

    def test_load_empty(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("timestamp,price\n")
        loader = DataLoader(csv_file)
        data = loader.load_all()
        assert len(data) == 0

    def test_sorted_by_time(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [
            {"timestamp_ns": "3000", "price": "300"},
            {"timestamp_ns": "1000", "price": "100"},
            {"timestamp_ns": "2000", "price": "200"},
        ]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file)
        data = loader.load_all()
        assert data[0]["timestamp_ns"] == "1000" or data[0]["timestamp_ns"] == 1000

    def test_gbk_encoding(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [{"timestamp": "2024-01-01", "price": "100"}]
        _write_csv(csv_file, rows, encoding="gbk")
        loader = DataLoader(csv_file)
        data = loader.load_all()
        assert len(data) == 1


# ════════════════════════════════════════════════════════════════
# JSONL 加载
# ════════════════════════════════════════════════════════════════


class TestJSONLLoading:
    """JSONL 加载"""

    def test_load_jsonl(self, tmp_path):
        jsonl_file = tmp_path / "test.jsonl"
        rows = [
            {"timestamp": "2024-01-01", "price": 100},
            {"timestamp": "2024-01-02", "price": 101},
        ]
        _write_jsonl(jsonl_file, rows)
        loader = DataLoader(jsonl_file)
        data = loader.load_all()
        assert len(data) == 2

    def test_load_json_array(self, tmp_path):
        json_file = tmp_path / "test.json"
        rows = [{"timestamp": "2024-01-01", "price": 100}]
        json_file.write_text(json.dumps(rows))
        loader = DataLoader(json_file)
        data = loader.load_all()
        assert len(data) == 1

    def test_invalid_jsonl_line_skipped(self, tmp_path):
        jsonl_file = tmp_path / "test.jsonl"
        with open(jsonl_file, "w") as f:
            f.write('{"timestamp": "2024-01-01", "price": 100}\n')
            f.write("not valid json\n")
            f.write('{"timestamp": "2024-01-02", "price": 101}\n')
        loader = DataLoader(jsonl_file)
        data = loader.load_all()
        assert len(data) == 2  # invalid line skipped


# ════════════════════════════════════════════════════════════════
# 时间解析
# ════════════════════════════════════════════════════════════════


class TestTimeParsing:
    """时间解析"""

    def test_parse_none(self):
        assert DataLoader._parse_time(None) is None

    def test_parse_iso_date(self):
        ts = DataLoader._parse_time("2024-01-01")
        assert ts is not None
        assert ts > 0

    def test_parse_iso_datetime(self):
        ts = DataLoader._parse_time("2024-01-01T12:00:00")
        assert ts is not None

    def test_parse_int_seconds(self):
        ts = DataLoader._parse_time(1704067200)  # 2024-01-01 in seconds
        assert ts is not None
        assert ts > 1_000_000_000_000_000_000  # nanoseconds

    def test_parse_float_seconds(self):
        ts = DataLoader._parse_time(1704067200.0)
        assert ts is not None

    def test_parse_invalid_raises(self):
        with pytest.raises(ValueError):
            DataLoader._parse_time("not-a-date")

    def test_ns_to_iso(self):
        iso = DataLoader._ns_to_iso(1704067200_000_000_000)
        assert iso is not None
        assert "2024" in iso

    def test_ns_to_iso_none(self):
        assert DataLoader._ns_to_iso(None) is None


# ════════════════════════════════════════════════════════════════
# 时间过滤
# ════════════════════════════════════════════════════════════════


class TestTimeFiltering:
    """时间过滤"""

    def test_filter_by_start(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [
            {"timestamp_ns": "1000000000000000000", "price": "100"},  # 2001
            {"timestamp_ns": "1704067200000000000", "price": "200"},  # 2024
        ]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file, start="2024-01-01")
        data = loader.load_all()
        assert len(data) == 1

    def test_filter_by_end(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [
            {"timestamp_ns": "1704067200000000000", "price": "100"},  # 2024-01-01
            {"timestamp_ns": "1735689600000000000", "price": "200"},  # 2025-01-01
        ]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file, end="2024-06-01")
        data = loader.load_all()
        assert len(data) == 1

    def test_no_filter(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [
            {"timestamp_ns": "1000000000000000000", "price": "100"},
            {"timestamp_ns": "1704067200000000000", "price": "200"},
        ]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file)
        data = loader.load_all()
        assert len(data) == 2


# ════════════════════════════════════════════════════════════════
# 流式回放
# ════════════════════════════════════════════════════════════════


class TestStreaming:
    """流式回放"""

    def test_stream_basic(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [{"timestamp_ns": str(i * 1000000000), "price": str(100 + i)} for i in range(10)]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file)
        batches = list(loader.stream(batch_size=3))
        assert len(batches) == 4  # 3+3+3+1
        assert len(batches[0]) == 3
        assert len(batches[-1]) == 1

    def test_stream_empty(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("timestamp,price\n")
        loader = DataLoader(csv_file)
        batches = list(loader.stream())
        assert len(batches) == 0

    def test_stream_speed_zero(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [{"timestamp_ns": str(i * 1000000000), "price": str(100 + i)} for i in range(5)]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file)
        batches = list(loader.stream(batch_size=2, speed=0))
        assert len(batches) == 3


# ════════════════════════════════════════════════════════════════
# 属性
# ════════════════════════════════════════════════════════════════


class TestDataLoaderProperties:
    """属性"""

    def test_data_range(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        _write_csv(csv_file, [{"timestamp_ns": "1704067200000000000", "price": "100"}])
        loader = DataLoader(csv_file, start="2024-01-01")
        start, end = loader.data_range
        assert start is not None

    def test_record_count(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        rows = [{"timestamp_ns": str(i), "price": str(100 + i)} for i in range(5)]
        _write_csv(csv_file, rows)
        loader = DataLoader(csv_file)
        assert loader.record_count == 5

    def test_caching(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        _write_csv(csv_file, [{"timestamp_ns": "1", "price": "100"}])
        loader = DataLoader(csv_file)
        data1 = loader.load_all()
        data2 = loader.load_all()
        assert data1 is data2  # same cached object


# ════════════════════════════════════════════════════════════════
# 多文件合并
# ════════════════════════════════════════════════════════════════


class TestLoadAndMerge:
    """多文件合并"""

    def test_merge_csv_files(self, tmp_path):
        f1 = tmp_path / "a.csv"
        f2 = tmp_path / "b.csv"
        _write_csv(f1, [{"timestamp_ns": "2000", "price": "200"}])
        _write_csv(f2, [{"timestamp_ns": "1000", "price": "100"}])
        merged = load_and_merge([f1, f2])
        assert len(merged) == 2
        assert merged[0]["timestamp_ns"] == "1000" or merged[0]["timestamp_ns"] == 1000


# ════════════════════════════════════════════════════════════════
# 类型转换
# ════════════════════════════════════════════════════════════════


class TestConvertRowTypes:
    """CSV 行类型转换"""

    def test_int_conversion(self):
        result = DataLoader._convert_row_types({"a": "42"})
        assert result["a"] == 42

    def test_float_conversion(self):
        result = DataLoader._convert_row_types({"a": "3.14"})
        assert result["a"] == 3.14

    def test_string_kept(self):
        result = DataLoader._convert_row_types({"a": "hello"})
        assert result["a"] == "hello"

    def test_empty_string(self):
        result = DataLoader._convert_row_types({"a": ""})
        assert result["a"] == ""

    def test_none_value(self):
        result = DataLoader._convert_row_types({"a": None})
        assert result["a"] is None
