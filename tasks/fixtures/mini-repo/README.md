# mini

A tiny library that formats and parses durations like `1h30m`.

## Usage

```python
from mini import parse, fmt
parse("1h30m")  # 5400
fmt(5400)       # "1h30m"
```
