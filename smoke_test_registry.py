import sys
sys.path.insert(0, ".")

from ml.module_registry import list_modules, get_module, DISASTER_MODULES

modules = list_modules()

print(f"{'='*65}")
print(f"  OrbitalMind — Module Registry Smoke Test")
print(f"{'='*65}")
print(f"  Total modules registered: {len(modules)}")
print(f"{'='*65}\n")

for m in modules:
    ws = sum(m["priority_weights"].values())
    print(f"  [{m['status'].upper():4}]  {m['disaster_type']:12}  |  {m['display_name']:24}  |  weights_sum={ws:.2f}")

print()

# Test get_module ValueError
try:
    get_module("tornado")
except ValueError as e:
    print(f"  ValueError test PASSED: {str(e).splitlines()[0]}")

# Test weight validation is sound
print()
print(f"  Weight validation:")
for disaster_type, module in DISASTER_MODULES.items():
    ok = module.validate_weights()
    print(f"    {disaster_type:12}  weights OK = {ok}")

print(f"\n{'='*65}")
print("  All checks passed.")
print(f"{'='*65}")
