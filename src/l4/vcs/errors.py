class GitError(Exception):
    def __init__(self, argv: list[str], returncode: int, stderr: str) -> None:
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        self.tries = 1  # how many times `Git._push` ran the command before giving up (L4-LCK-001)
        first = stderr.strip().splitlines()[:1]
        super().__init__(f"{' '.join(argv)} failed ({returncode})" + (f": {first[0]}" if first else ""))
