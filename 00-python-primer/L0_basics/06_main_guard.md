# `if __name__ == "__main__"` 入口约定

## 是什么
每个 .py 文件都有一个特殊的模块级变量 `__name__`:
- 文件**直接运行** (`python foo.py`) → `__name__ == "__main__"`
- 文件**被 import** (`import foo`) → `__name__ == "foo"`

因此常用 `if __name__ == "__main__":` 守护"只在直接运行时执行"的代码。

## 为什么要用
- 让 .py 文件既能被 `python XX.py` 跑,又能被 `from XX import func` 复用
- 项目里所有 demo 文件都用它
- 不写这行, `import` 时副作用 (print / 网络调用) 全跑

## 语法骨架

```python
# 文件: mymodule.py
def helper():
    return "可用"

if __name__ == "__main__":
    # 只有 python mymodule.py 才走这里
    print(helper())
```

```bash
python mymodule.py        # 跑打印
python -c "import mymodule"  # 不打印
```

## 项目里的真实例子

```python
# 所有 17 个项目文件的末尾, 都是这个结构
if __name__ == "__main__":
    setup()
    banner("1. ...")
    demo_basic()
    banner("2. ...")
    demo_advanced()
```

## 常见坑

1. **缩进错误**: `if` 块里的代码必须缩进 4 空格
2. **`__name__` 不是字符串**? 它就是字符串 `"__main__"` 或模块名
3. **用 `-m` 跑也算 main**: `python -m mypackage.mymodule` 时 `__name__ == "__main__"`

## Java/Go 对比

| 概念 | Java | Go | Python |
|---|---|---|---|
| 入口 | `public static void main(String[])` | `func main()` | `if __name__ == "__main__":` |
| 模块 vs 入口 | 类 + main 分开 | `func main()` 强约束 | 一个文件既能当模块也能当入口 |
