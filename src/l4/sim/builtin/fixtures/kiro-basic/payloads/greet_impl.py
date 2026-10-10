def farewell(name):
    return f"Goodbye, {name.strip()}!"


def greet(name):
    if not name.strip():
        raise ValueError("a greeting needs a name")
    return f"Hello, {name.strip()}!"
