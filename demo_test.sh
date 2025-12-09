#!/bin/bash

# Script to run pytest commands in a loop
# Usage: ./run_tests.sh <number_of_loops>

# Check if arguments are provided
if [ $# -lt 1 ]; then
    echo "Usage: $0 <number_of_loops>"
    echo "Example: $0 5"
    return 1 2>/dev/null || { echo "Script stopped."; return; }
fi

# Get the number of loops from command line argument
LOOPS=$1

# Get timeout from second argument, default to 300 if not provided
if [ -n "$2" ]; then
    TIMEOUT=$2
else
    TIMEOUT=600 # Default timeout in seconds
fi

# Validate that the argument is a positive integer
if ! [[ "$LOOPS" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: Please provide a positive integer for the number of loops"
    echo "Usage: $0 <number_of_loops>"
    return
fi

# Validate that timeout is a positive integer
if ! [[ "$TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: Please provide a positive integer for timeout_seconds"
    echo "Usage: $0 <number_of_loops> [timeout_seconds]"
    return
fi

# Set display environment variable for GUI applications
export DISPLAY=:0

# Create timestamp for this test session
SESSION_TIMESTAMP=$(date +"%Y.%m.%d-%H.%M.%S")
SESSION_FOLDER_NAME=$(date +"%Y-%m-%d-%H-%M-%S")
RESULTS_DIR="./results/$SESSION_FOLDER_NAME"

# Create results directory
mkdir -p "$RESULTS_DIR"

echo "Running pytest commands $LOOPS times..."
echo "Results will be saved in: $RESULTS_DIR"

# Function to run test and capture results
run_test_and_capture() {
    local test_name=$1
    local loop_num=$2
    local loop_output_file=$3
    
    echo "Running $test_name (loop $loop_num)..."
    
    # Add test header to loop output file
    echo "=========================================" >> "$loop_output_file"
    echo "Test: $test_name - Loop $loop_num" >> "$loop_output_file"
    echo "Timestamp: $(date)" >> "$loop_output_file"
    echo "=========================================" >> "$loop_output_file"
    
    # Run pytest and capture output to loop file, with --saveimage=1
    timeout $TIMEOUT pytest --verbose tapp.py::$test_name --savemeta=1 --saveimage=1 2>&1 | tee -a "$loop_output_file"
    exit_code=${PIPESTATUS[0]}
    if [ "$exit_code" -eq 124 ]; then
        timeout_flag=true
    else
        timeout_flag=false
    fi
    echo "" >> "$loop_output_file"
    echo "--- End of $test_name Loop $loop_num (timeout = [$timeout_flag]) ---" >> "$loop_output_file"
    echo "" >> "$loop_output_file"
}


# Loop through the specified number of times
for ((i=1; i<=LOOPS; i++)); do
    echo "=========================================="
    echo "Starting loop $i of $LOOPS"
    echo "=========================================="
    
    # Create current loop timestamp
    LOOP_TIMESTAMP=$(date +"%Y-%m-%d-%H-%M-%S")

    # Create per-loop results directory
    LOOP_RESULTS_DIR="$RESULTS_DIR/Loop_#${i}_${LOOP_TIMESTAMP}"
    mkdir -p "$LOOP_RESULTS_DIR"

    # Create individual loop output file with current timestamp
    LOOP_OUTPUT_FILE="$LOOP_RESULTS_DIR/Logs_${LOOP_TIMESTAMP}.txt"

    # Initialize the loop output file
    echo "=========================================" > "$LOOP_OUTPUT_FILE"
    echo "HMI Test Loop $i of $LOOPS" >> "$LOOP_OUTPUT_FILE"
    echo "Loop Started: $LOOP_TIMESTAMP" >> "$LOOP_OUTPUT_FILE"
    echo "Session: $SESSION_TIMESTAMP" >> "$LOOP_OUTPUT_FILE"
    echo "=========================================" >> "$LOOP_OUTPUT_FILE"
    echo "" >> "$LOOP_OUTPUT_FILE"

    echo "Loop output file: $LOOP_OUTPUT_FILE"

    run_test_and_capture "test_pdfd" "$i" "$LOOP_OUTPUT_FILE"
    run_test_and_capture "test_fid" "$i" "$LOOP_OUTPUT_FILE"

    # Move all JSON and image files from ./results to the loop results directory
    find ./results -maxdepth 1 \( -name '*.json' -o -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.bmp' \) -exec mv {} "$LOOP_RESULTS_DIR" \;
    
    # Add completion marker to loop file
    echo "=========================================" >> "$LOOP_OUTPUT_FILE"
    echo "Loop $i Completed: $(date)" >> "$LOOP_OUTPUT_FILE"
    echo "=========================================" >> "$LOOP_OUTPUT_FILE"

    echo "Loop $i completed"
    echo ""
    sleep 2 # Short pause between loops
done

echo "=========================================="
echo "All $LOOPS loops completed!"
echo "Results saved in: $RESULTS_DIR"
echo "Individual loop files: logs_<timestamp>.txt"
echo "=========================================="

# Run tsum.py to generate summary after all loops
echo "Generating summary with tsum.py..."
python3 tsum.py "$RESULTS_DIR"
echo "Summary generated: $RESULTS_DIR/summary.txt"