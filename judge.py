import os
import subprocess

# Paths
submission = "submissions/user.cpp"
executable = "submissions/user.out"
testcase_dir = "testcases/"

# Compile
compile_cmd = ["g++", submission, "-o", executable]
compile = subprocess.run(compile_cmd, capture_output=True, text=True)

if compile.returncode != 0:
    print("❌ Compilation Error:")
    print(compile.stderr)
    exit(1)

# Helper function to run test cases
def run_test(input_file, expected_file):
    with open(input_file, "r") as infile, open(expected_file, "r") as expfile:
        expected = expfile.read().strip()
        result = subprocess.run([f"./{executable}"], stdin=infile, capture_output=True, text=True)
        output = result.stdout.strip()
        return output == expected, output, expected

# Public test cases
print("✅ Public Test Cases:")
for i in range(1, 3):
    ok, out, exp = run_test(f"{testcase_dir}/input{i}.txt", f"{testcase_dir}/output{i}.txt")
    print(f"Test {i}: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(f"  Expected: {exp}, Got: {out}")

# Hidden test cases
print("\n🔒 Hidden Test Cases:")
for i in range(1, 3):
    ok, _, _ = run_test(f"{testcase_dir}/hidden_input{i}.txt", f"{testcase_dir}/hidden_output{i}.txt")
    print(f"Hidden Test {i}: {'PASS' if ok else 'FAIL'}")
