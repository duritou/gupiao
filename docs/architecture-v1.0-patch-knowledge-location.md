# v1.0 Patch: Knowledge 基础设施移至 infrastructure

> **优先级**: Phase 4 实现时执行  
> **原则**: Knowledge 数据是资源（根目录），Knowledge 基础设施是代码（src/infrastructure）

---

## 修正

```
之前:
  knowledge/
  ├── loader.py       ← 代码
  ├── indexer.py      ← 代码
  ├── search.py       ← 代码
  ├── watcher.py      ← 代码
  ├── industry/       ← 数据
  └── ...

修正后:
  knowledge/                    # 纯数据（YAML 资源）
  ├── industry/
  ├── macro/
  ├── concepts/
  ├── finance/
  ├── reports/
  ├── policy/
  ├── strategy/
  ├── books/
  ├── papers/
  └── glossary/

  src/infrastructure/knowledge/ # 基础设施代码
  ├── __init__.py
  ├── loader.py
  ├── indexer.py
  ├── search.py
  └── watcher.py
```

---

> **Patch 完成。数据归数据，代码归代码。**
