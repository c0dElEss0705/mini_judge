import os
import subprocess
import psutil
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
import threading
import time
from queue import Queue

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = "submissions"
EXECUTABLE = os.path.join(UPLOAD_FOLDER, "user.out")
TESTCASE_DIR = "testcases"
PROBLEM_STATEMENT_FILE = "problem.ps"
ALLOWED_EXTENSIONS = {'cpp', 'cc', 'cxx'}
MAX_FILE_SIZE = 1024 * 1024  # 1MB
MAX_MEMORY_LIMIT = 256 * 1024 * 1024  # 256MB
MAX_CPU_TIME = 5  # seconds

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Ensure dirs exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TESTCASE_DIR, exist_ok=True)

# Batch processing queue
batch_queue = Queue()
results_dict = {}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_problem_statement():
    """Read and return the problem statement from file"""
    try:
        if os.path.exists(PROBLEM_STATEMENT_FILE):
            with open(PROBLEM_STATEMENT_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return "# Problem Statement\n\nThis is a sample problem statement. Create a 'problem.ps' file in the same directory as app.py to display your actual problem statement."
    except Exception as e:
        return f"# Problem Statement\n\nError reading problem statement file: {str(e)}"

def compile_cpp(filepath):
    compile_cmd = ["g++", filepath, "-o", EXECUTABLE, "-std=c++11"]
    try:
        result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "Compilation timed out (30s)"

def run_test(input_file, expected_file, submission_id, test_id):
    try:
        with open(input_file, "r") as infile, open(expected_file, "r") as expfile:
            expected = expfile.read().strip()
            input_data = infile.read()
            
            # Start process
            process = subprocess.Popen(
                [EXECUTABLE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=UPLOAD_FOLDER
            )
            
            try:
                start_time = time.time()
                memory_used = 0
                
                # Send input and get output with timeout
                stdout, stderr = process.communicate(input=input_data, timeout=MAX_CPU_TIME)
                output = stdout.strip()
                
                # Check memory usage after process completes
                try:
                    if os.name == 'nt':  # Windows
                        mem_info = psutil.Process(process.pid).memory_info()
                        memory_used = mem_info.rss
                    else:  # Unix-like systems
                        # For Unix, we need to monitor differently
                        memory_used = 0
                        for child in psutil.Process(process.pid).children(recursive=True):
                            memory_used += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    memory_used = 0
                
                # Check if memory limit exceeded
                if memory_used > MAX_MEMORY_LIMIT:
                    return False, f"Memory limit exceeded ({memory_used} bytes)", expected, memory_used
                
                if process.returncode != 0:
                    return False, f"Runtime error (return code {process.returncode}): {stderr}", expected, memory_used
                
                return output == expected, output, expected, memory_used
                
            except subprocess.TimeoutExpired:
                process.kill()
                return False, "Time limit exceeded (5s)", expected, 0
            except Exception as e:
                process.kill()
                return False, f"Unexpected error: {str(e)}", expected, 0
                
    except FileNotFoundError:
        return False, "Test case files not found", "", 0
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", "", 0

def grade_submission(filepath, submission_id):
    """Grade a single submission and store results"""
    results = {
        'submission_id': submission_id,
        'filename': os.path.basename(filepath),
        'compile_status': 'pending',
        'test_results': [],
        'memory_usage': [],
        'overall_status': 'pending',
        'status': 'processing'
    }
    
    # Update results dict
    results_dict[submission_id] = results
    
    # Compile
    code, stderr = compile_cpp(filepath)
    if code != 0:
        results['compile_status'] = 'error'
        results['compile_error'] = stderr
        results['overall_status'] = 'compile_error'
        results['status'] = 'completed'
        return
    
    results['compile_status'] = 'success'
    
    # Run public test cases
    public_passed = 0
    public_total = 0
    
    # Find all test cases
    test_cases = []
    for f in os.listdir(TESTCASE_DIR):
        if f.startswith('input') and f.endswith('.txt'):
            try:
                test_cases.append(int(f[5:-4]))
            except ValueError:
                continue
    
    for i in sorted(test_cases):
        input_file = f"{TESTCASE_DIR}/input{i}.txt"
        expected_file = f"{TESTCASE_DIR}/output{i}.txt"
        
        if os.path.exists(input_file) and os.path.exists(expected_file):
            public_total += 1
            ok, out, exp, mem_used = run_test(input_file, expected_file, submission_id, f"public_{i}")
            
            result = {
                "type": "Public",
                "case": i,
                "status": "PASS" if ok else "FAIL",
                "expected": exp,
                "got": out,
                "memory_used": mem_used
            }
            
            results['test_results'].append(result)
            results['memory_usage'].append(mem_used)
            
            if ok:
                public_passed += 1
    
    # Run hidden test cases
    hidden_passed = 0
    hidden_total = 0
    
    # Find all hidden test cases
    hidden_test_cases = []
    for f in os.listdir(TESTCASE_DIR):
        if f.startswith('hidden_input') and f.endswith('.txt'):
            try:
                hidden_test_cases.append(int(f[11:-4]))
            except ValueError:
                continue
    
    for i in sorted(hidden_test_cases):
        input_file = f"{TESTCASE_DIR}/hidden_input{i}.txt"
        expected_file = f"{TESTCASE_DIR}/hidden_output{i}.txt"
        
        if os.path.exists(input_file) and os.path.exists(expected_file):
            hidden_total += 1
            ok, out, exp, mem_used = run_test(input_file, expected_file, submission_id, f"hidden_{i}")
            
            result = {
                "type": "Hidden",
                "case": i,
                "status": "PASS" if ok else "FAIL",
                "memory_used": mem_used
            }
            
            results['test_results'].append(result)
            results['memory_usage'].append(mem_used)
            
            if ok:
                hidden_passed += 1
    
    # Calculate overall status
    total_tests = public_total + hidden_total
    total_passed = public_passed + hidden_passed
    
    if total_tests == 0:
        results['overall_status'] = 'no_tests'
    elif total_passed == total_tests:
        results['overall_status'] = 'success'
    else:
        results['overall_status'] = 'partial'
    
    results['score'] = f"{total_passed}/{total_tests}"
    results['public_score'] = f"{public_passed}/{public_total}" if public_total > 0 else "N/A"
    results['hidden_score'] = f"{hidden_passed}/{hidden_total}" if hidden_total > 0 else "N/A"
    results['status'] = 'completed'

def batch_worker():
    """Worker thread for processing batch submissions"""
    while True:
        if not batch_queue.empty():
            filepath, submission_id = batch_queue.get()
            try:
                grade_submission(filepath, submission_id)
            except Exception as e:
                print(f"Error grading submission {submission_id}: {str(e)}")
                results_dict[submission_id] = {
                    'submission_id': submission_id,
                    'filename': os.path.basename(filepath),
                    'compile_status': 'error',
                    'compile_error': f'Grading failed: {str(e)}',
                    'overall_status': 'error',
                    'status': 'completed'
                }
            batch_queue.task_done()
        time.sleep(0.1)

# Start batch processing thread
batch_thread = threading.Thread(target=batch_worker, daemon=True)
batch_thread.start()

@app.route("/")
def index():
    problem_statement = get_problem_statement()
    return render_template("index.html", problem_statement=problem_statement)

@app.route("/upload", methods=["POST"])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            
            # Generate unique submission ID
            submission_id = str(int(time.time() * 1000))
            
            # Initialize result entry
            results_dict[submission_id] = {
                'submission_id': submission_id,
                'filename': filename,
                'compile_status': 'pending',
                'test_results': [],
                'memory_usage': [],
                'overall_status': 'pending',
                'status': 'processing'
            }
            
            # Add to batch queue
            batch_queue.put((filepath, submission_id))
            
            return jsonify({
                'submission_id': submission_id,
                'filename': filename,
                'message': 'File uploaded and queued for grading'
            })
        
        return jsonify({'error': 'Invalid file type. Only .cpp, .cc, and .cxx files are allowed.'}), 400
    except Exception as e:
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route("/status/<submission_id>")
def get_status(submission_id):
    if submission_id in results_dict:
        result = results_dict[submission_id]
        # If grading is completed, make sure to return the final status
        if result.get('status') == 'completed':
            return jsonify(result)
        else:
            # Return processing status with current progress
            progress_data = {
                'status': 'processing',
                'submission_id': submission_id,
                'filename': result.get('filename', ''),
                'compile_status': result.get('compile_status', 'pending'),
                'test_count': len(result.get('test_results', [])),
                'message': 'Grading in progress...'
            }
            return jsonify(progress_data)
    
    # If submission ID not found, it might not be processed yet
    return jsonify({'status': 'processing', 'message': 'Submission queued for processing'})

@app.route("/batch_upload", methods=["POST"])
def batch_upload():
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files')
        if not files or all(file.filename == '' for file in files):
            return jsonify({'error': 'No files selected'}), 400
        
        submission_ids = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)
                
                # Generate unique submission ID
                submission_id = str(int(time.time() * 1000) + len(submission_ids))
                submission_ids.append(submission_id)
                
                # Initialize result entry
                results_dict[submission_id] = {
                    'submission_id': submission_id,
                    'filename': filename,
                    'compile_status': 'pending',
                    'test_results': [],
                    'memory_usage': [],
                    'overall_status': 'pending',
                    'status': 'processing'
                }
                
                # Add to batch queue
                batch_queue.put((filepath, submission_id))
        
        return jsonify({
            'submission_ids': submission_ids,
            'message': f'{len(submission_ids)} files uploaded and queued for grading'
        })
    except Exception as e:
        return jsonify({'error': f'Batch upload failed: {str(e)}'}), 500

if __name__ == "__main__":
    app.run(debug=True)