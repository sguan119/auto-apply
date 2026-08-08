"""autoapply — fully automated job-application tool.

Top-level namespace so the entry layers (`autoapply.cli`, and a future
`autoapply.web`) and the interface-agnostic `autoapply.core` package never
occupy generic top-level import names like `core`/`cli`/`web`, where any
dependency shipping a module of the same name would shadow them.
"""
