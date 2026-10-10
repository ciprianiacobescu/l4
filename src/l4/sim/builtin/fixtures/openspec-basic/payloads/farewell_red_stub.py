def greet(name):
    if not name.strip():
        raise ValueError("a greeting needs a name")
    return f"Hello, {name.strip()}!"


def farewell(name):
    raise NotImplementedError
