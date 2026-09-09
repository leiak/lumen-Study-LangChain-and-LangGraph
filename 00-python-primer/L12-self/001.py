
rows = [
        {"id": i, "value": f"row-{i}", "data": "x" * 50}
        for i in range(5)
    ]
summary = f"查询返回 {len(rows)} 行, 前 3 行预览: {rows[:3]}"

print(summary,rows)
