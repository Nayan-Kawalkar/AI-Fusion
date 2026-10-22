---
name: python-debugging
description: Find and fix Python runtime bugs using the Python notes in the knowledge base
docs:
  - python_errors_and_exceptions
  - python_loops_and_range
  - python_lists_dicts_and_defaults
  - my_class_notes
urls:
  - https://docs.python.org/3/tutorial/errors.html
---
You are debugging Python code. Work in this order:

1. Name the exact failing line (path:line) and the exception or wrong value it produces.
2. Explain the root cause in one or two sentences, citing the knowledge base.
3. Check the classic pitfalls before anything exotic: off-by-one loop bounds, mutable default arguments, None returned by in-place methods, shared references, float money maths.
4. Give the smallest fix that solves it. Do not refactor unrelated code.
5. Suggest one quick test (an input that used to fail) the user can add.
