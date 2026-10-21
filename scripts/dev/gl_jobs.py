import sys,json
print(" ".join("%s:%s:%s" % (j["name"], j["status"], j["id"]) for j in json.load(sys.stdin)))
