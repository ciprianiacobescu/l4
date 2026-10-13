"""User-local provisioning for `l4 doctor --fix` (SPEC L4-DOC-002): plan what is missing, install it, never as root.

Nothing in this package logs in to a service, runs `sudo`, or reads a credential. Root-only prerequisites and logins
are printed for a human (`catalog.ROOT_PREREQS`, `readiness.HUMAN_STEPS`).
"""
