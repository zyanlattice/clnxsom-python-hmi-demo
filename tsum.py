import os
import sys
import re
import shutil
import urllib.parse
from pathlib import Path

def find_log_file(loop_dir):
    for fname in os.listdir(loop_dir):
        if fname.lower().startswith("logs_") and fname.lower().endswith(".txt"):
            return os.path.join(loop_dir, fname)
    return None

def parse_log(log_path):
    results = []
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"Test:\s*(\w+)\s*-\s*Loop\s*(\d+)", line)
        if m:
            test_type = m.group(1)
            loop_num = m.group(2)
            # Find end of this test block
            end_pat = re.compile(rf"End of {test_type} Loop {loop_num}")
            j = i
            while j < len(lines) and not end_pat.search(lines[j]):
                j += 1
            # After finding the end marker, extract timeout value from lines[j]
            timeout_flag = re.search(r"timeout = \[(true|false)\]", lines[j]).group(1) if j < len(lines) and re.search(r"timeout = \[(true|false)\]", lines[j]) else "false"
            # Search for summary line in this block
            failed = passed = error = 0
            time_sec = None
            for k in range(i, j):
                l = lines[k].strip()
                if l.startswith("=") and l.endswith("=") and "in" in l:
                    m_failed = re.search(r"(\d+) failed", l)
                    m_passed = re.search(r"(\d+) passed", l)
                    m_error = re.search(r"(\d+) error", l)
                    m_time = re.search(r"in ([\d\.]+)s", l)
                    if m_failed:
                        failed = int(m_failed.group(1))
                    if m_passed:
                        passed = int(m_passed.group(1))
                    if m_error:
                        error = int(m_error.group(1))
                    if m_time:
                        time_sec = float(m_time.group(1))
                    # Only add if time_sec is found
                    if time_sec is not None:
                        break
            if test_type and loop_num and time_sec is not None:
                results.append([int(loop_num), test_type, failed, passed, error, f"{time_sec:.2f}", timeout_flag])
            i = j + 1
        else:
            i += 1
    return results

def get_loop_number_from_log(log_path):
    """
    Read the loop number from the log header lines like:
    "Test: test_fd - Loop 1"
    Returns the first loop number found as a string, or None.
    """
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.search(r"Test:\s*\w+\s*-\s*Loop\s*(\d+)", line)
                if m:
                    return m.group(1)
    except Exception as e:
        print(f"Error reading loop number from {log_path}: {e}")
    return None

def extract_failed_tests_with_items(log_path):
    """
    Extract failed test details including test name and which parametrized item failed.
    Returns list of tuples: (test_name, failed_item_index)
    Example: ('test_pd', '2') means test_pd[2] failed
    """
    failed_tests = []
    lines = []
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # We need the order from top-to-bottom of the collected items to compute the item index
    # Example lines:
    # tapp.py::test_fd[features0-./images/face_detect/fd_5_pax_100cm.jpg-5] FAILED [ 60%]
    order_counter = {}
    current_loop = None
    # Track the most recent header: Test: <name> - Loop <N>
    # Anchor to the exact header line to avoid picking up folder-like text
    header_pat = re.compile(r"^\s*Test:\s*[\w_]+\s*-\s*Loop\s*(\d+)\s*$")
    for raw_line in lines:
        line = raw_line.strip()  # normalize DOS/Unix line endings and whitespace
        hm = header_pat.search(line)
        if hm:
            current_loop = hm.group(1)
            continue
        if 'tapp.py::' in line and 'test_' in line and '[' in line and ']' in line:
            m = re.search(r'tapp\.py::([\w_]+)\[(.*?)\]\s+(PASSED|FAILED|ERROR)', line)
            if not m:
                continue
            test_name = m.group(1)
            param_payload = m.group(2)
            outcome = m.group(3)
            # Increment order for this test_name within the current loop header context
            key = (current_loop or 'unknown', test_name)
            order_counter[key] = order_counter.get(key, 0) + 1
            current_item_index = str(order_counter[key])
            # Extract the full image path within payload, including directories, ending with a common image extension.
            # Examples:
            #  - ./images/registration/ed-sheeran/img_pax-1_ed-sheeran.jpg
            #  - ./images/person/img_pax-4.jpg
            img_label = None
            # Prefer paths under ./images/... ending in an image extension.
            full_path_match = re.search(r'(\./images/[^\]]+\.(?:jpg|jpeg|png|bmp))', param_payload, re.IGNORECASE)
            if full_path_match:
                from_path = full_path_match.group(1)
                # Normalize to forward slashes and drop leading './' when displaying
                normalized = from_path.replace('\\', '/').lstrip('./')
                img_label = '/' + normalized
            else:
                # Fallback: any token ending with a common image extension
                ext_match = re.search(r'([^\s\]]+\.(?:jpg|jpeg|png|bmp))', param_payload, re.IGNORECASE)
                if ext_match:
                    from_path = ext_match.group(1)
                    normalized = from_path.replace('\\', '/').lstrip('./')
                    # Prepend '/' to match desired display style
                    img_label = '/' + normalized
                else:
                    img_label = param_payload

            if outcome == 'FAILED':
                failed_tests.append((test_name, current_item_index, img_label, current_loop or 'Unknown'))

    # If nothing matched, fallback to broad FAILED markers
    if not failed_tests:
        content = ''.join(lines)
        for line in content.split('\n'):
            if 'FAILED' in line and 'tapp.py::' in line:
                match = re.search(r'FAILED\s+tapp\.py::([\w_]+)', line)
                if match:
                    test_name = match.group(1)
                    failed_tests.append((test_name, '1', None, current_loop or 'Unknown'))

    return failed_tests

def find_images_for_test(loop_dir, test_name):
    """
    Find image files associated with a failed test.
    Returns list of image file paths.
    """
    images = []
    # Map pytest test names to expected image filename prefixes
    prefix_map = {
        'test_fd': 't_fd',
        'test_pd': 't_pd',
        'test_od': 't_od',
        'test_person': 't_person',
        'test_distance': 't_distance',
        'test_occlusion': 't_occlusion',
        # Add other known tests here as needed
    }
    # Derive possible prefixes to search for
    possible_prefixes = set()
    if test_name in prefix_map:
        possible_prefixes.add(prefix_map[test_name])
    # Also consider direct t_testname and t_short forms
    possible_prefixes.add(f"t_{test_name}")
    short = None
    if test_name.startswith('test_') and len(test_name) > 5:
        short = test_name[5:]
        possible_prefixes.add(f"t_{short}")
    try:
        for fname in os.listdir(loop_dir):
            if fname.endswith(('.jpg', '.png', '.jpeg', '.bmp')):
                for pref in possible_prefixes:
                    if fname.startswith(f"{pref}_") or fname.startswith(pref):
                        images.append(os.path.join(loop_dir, fname))
                        break
    except Exception as e:
        print(f"Error scanning {loop_dir}: {e}")
    return images

def generate_html_report(test_folder, output_html="report.html"):
    """
    Generate HTML report with failed tests and their images.
    """
    failed_entries = []
    entry_num = 1
    
    print(f"Scanning test folder: {test_folder}")
    
    # Process each loop directory
    for loop_name in sorted(os.listdir(test_folder)):
        loop_path = os.path.join(test_folder, loop_name)
        if not os.path.isdir(loop_path):
            continue
        
        # Find and parse log file
        log_file = find_log_file(loop_path)
        if not log_file:
            print(f"  No log file found in {loop_name}")
            continue

        # Prefer loop number from the log content; fallback to folder name
        loop_num = get_loop_number_from_log(log_file)
        if not loop_num:
            loop_match = re.search(r'Loop_#(\d+)', loop_name)
            loop_num = loop_match.group(1) if loop_match else "Unknown"
        
        print(f"  Processing loop {loop_num}")
        failed_tests = extract_failed_tests_with_items(log_file)
        print(f"    Failed tests found: {len(failed_tests)} items")
        for ft in failed_tests[:10]:
            try:
                tn, idx, lbl, lp = ft if len(ft) >= 4 else (ft[0], ft[1], ft[2] if len(ft)>2 else None, 'Unknown')
                print(f"      -> {tn}[{idx}] loop={lp} label={lbl}")
            except Exception:
                print(f"      -> tuple={ft}")
        
        # If no FAILED markers, try to extract from parse_log results
        if not failed_tests:
            results = parse_log(log_file)
            for result in results:
                # result format: [loop_num, test_type, failed, passed, error, time, timeout]
                if result[2] > 0:  # failed count > 0
                    failed_tests.append((result[1], '0'))  # test_type with default item 0
            if failed_tests:
                print(f"    Failed tests from parse_log: {failed_tests}")
        
        # For each failed test, find associated images
        for ft in failed_tests:
            # tuple: (test_name, item_index, img_label, loop_num_from_log)
            if len(ft) >= 4:
                test_name, item_index, img_label, loop_from_log = ft
            else:
                test_name, item_index = ft[:2]
                img_label = ft[2] if len(ft) > 2 else None
                loop_from_log = loop_num
            images = find_images_for_test(loop_path, test_name)
            print(f"    Images for {test_name}[{item_index}] (loop {loop_from_log}): {len(images)} found")
            # If we have multiple images, sort by name to be deterministic and pick the Nth by item_index
            selected_image_rel = None
            selected_exists = False
            if images:
                images_sorted = sorted(images)
                idx = max(1, int(item_index)) - 1 if str(item_index).isdigit() else 0
                if idx < len(images_sorted):
                    image_path = images_sorted[idx]
                    selected_image_rel = os.path.relpath(image_path, test_folder)
                    selected_exists = os.path.exists(image_path)
                else:
                    # Fallback to first image if index out of range
                    image_path = images_sorted[0]
                    selected_image_rel = os.path.relpath(image_path, test_folder)
                    selected_exists = os.path.exists(image_path)
            else:
                # Still add entry even without image, so we know the test failed
                selected_image_rel = None
                selected_exists = False

            failed_entries.append({
                'no': entry_num,
                'loop': loop_from_log,
                'test': test_name,
                'item': item_index,
                'test_image': img_label,
                'image': selected_image_rel,
                'image_exists': selected_exists
            })
            print(f"    Added entry #{entry_num}: loop={loop_from_log}, test={test_name}, item={item_index}, test_image={img_label}, image={'yes' if selected_exists else 'no'}")
            entry_num += 1
    
    # Sort entries in ascending order: loop (numeric when possible), then test, then item
    def _loop_key(v):
        try:
            return int(v['loop'])
        except Exception:
            return 999999
    def _item_key(v):
        try:
            return int(v['item'])
        except Exception:
            return 0
    failed_entries.sort(key=lambda v: (_loop_key(v), v['test'], _item_key(v)))

    print(f"Total failed entries found: {len(failed_entries)}")

    # Prepare 'report images' directory and copy required images from the image repo if available
    # Expect user to pass the base folder path like '/home/.../results/2025-12-06-10-48-00'
    report_dir = Path(test_folder)
    report_images_dir = report_dir / "report images"
    copied_image_map = {}

    # Try to infer images repo from project structure or environment
    # Allow override via environment variable CLNX_IMAGES_REPO
    images_repo = os.environ.get("CLNX_IMAGES_REPO")
    if not images_repo:
        # Heuristic: project root is parent of 'results' folder; images at sibling 'images'
        # e.g., /home/lattice/Documents/clnxsom-python-hmi/results/<timestamp>
        # images at /home/lattice/Documents/clnxsom-python-hmi/images
        p = report_dir
        if p.name == "results" and p.parent:
            images_repo = str(p.parent / "images")
        else:
            # If we're inside the timestamp folder, parent is results
            if p.parent.name == "results" and p.parent.parent:
                images_repo = str(p.parent.parent / "images")

    if images_repo and os.path.isdir(images_repo):
        report_images_dir.mkdir(parents=True, exist_ok=True)
        print(f"Copying images into: {report_images_dir}")
        for entry in failed_entries:
            # entry['test_image'] looks like '/images/registration/ed-sheeran/img_pax-1_ed-sheeran.jpg'
            img_rel = entry.get('test_image')
            if not img_rel or not isinstance(img_rel, str):
                continue
            # Normalize and strip leading '/images/'
            img_rel_norm = img_rel.replace('\\', '/').lstrip('/')
            if not img_rel_norm.startswith('images/'):
                # If it was just a filename, skip copy
                continue
            rel_under_repo = img_rel_norm[len('images/'):]
            src_path = Path(images_repo) / rel_under_repo
            if src_path.is_file():
                dst_path = report_images_dir / src_path.name
                # Avoid re-copy if already copied
                if not dst_path.exists():
                    try:
                        shutil.copy2(src_path, dst_path)
                        print(f"  Copied {src_path} -> {dst_path}")
                    except Exception as e:
                        print(f"  Failed to copy {src_path}: {e}")
                # Record mapping for HTML use
                copied_image_map[img_rel] = str(dst_path.relative_to(report_dir))
            else:
                print(f"  Source image not found: {src_path}")
    else:
        if images_repo:
            print(f"Images repo not found: {images_repo}")
        else:
            print("Images repo path not determined; skipping image copy.")
    
    # Generate HTML
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Failure Report</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #333;
            text-align: center;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        th {
            background-color: #d32f2f;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            border: 1px solid #999;
        }
        td {
            padding: 12px;
            border: 1px solid #ddd;
            vertical-align: top;
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        tr:hover {
            background-color: #f0f0f0;
        }
        .no-column {
            width: 5%;
            text-align: center;
        }
        .loop-column {
            width: 10%;
            text-align: center;
        }
        .test-column {
            width: 15%;
        }
        .item-column {
            width: 10%;
            text-align: center;
        }
        .testimg-column {
            width: 20%;
            word-break: break-all;
        }
        .image-column {
            width: 55%;
        }
        img {
            max-width: 100%;
            max-height: 400px;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin-top: 8px;
        }
        /* Ensure both Test Image and Extracted Image scale identically */
        .report-img {
            width: 100%;
            height: 240px;
            object-fit: contain;
        }
        .no-image {
            color: #999;
            font-style: italic;
        }
        .summary {
            margin-bottom: 20px;
            padding: 10px;
            background-color: #e3f2fd;
            border-left: 4px solid #2196f3;
        }
    </style>
</head>
<body>
    <h1>Test Failure Report</h1>
"""
    
    # Add summary
    html_content += f"""    <div class="summary">
        <strong>Total Failed Entries:</strong> {len(failed_entries)}<br>
        <strong>Report Generated:</strong> {os.path.basename(test_folder)}
    </div>
    
    <table>
        <thead>
            <tr>
                <th style="width: 5%;">No.</th>
                <th class="loop-column">Loop Number</th>
                <th class="test-column">Fail Test Item</th>
                <th class="item-column">Failed Item</th>
                <th class="testimg-column">Test Image</th>
                <th class="image-column">Extracted Image</th>
            </tr>
        </thead>
        <tbody>
"""
    
    # Add table rows with sequential numbering independent of data order
    for idx, entry in enumerate(failed_entries, start=1):
        if entry['image'] and entry['image_exists']:
            # URL-encode special characters for browser compatibility (e.g., # -> %23)
            encoded_src = urllib.parse.quote(entry["image"].replace('\\', '/'), safe='/._-')
            image_html = f'<img class="report-img" src="{encoded_src}" alt="Extracted image">'
        else:
            image_html = '<span class="no-image">No image captured</span>'
        
        # If we copied the test image into 'report images', render the image only (no path text)
        test_img_disp = entry.get('test_image') or 'N/A'
        copied_rel = copied_image_map.get(entry.get('test_image'))
        if copied_rel:
            copied_src = urllib.parse.quote(copied_rel.replace('\\', '/'), safe='/._-')
            test_img_disp_html = f"<img class=\"report-img\" src=\"{copied_src}\" alt=\"Original test image\">"
        else:
            # If no copied image, still avoid showing the raw path; show placeholder
            test_img_disp_html = '<span class="no-image">Image not available</span>'

        html_content += f"""            <tr>
                <td class="no-column">{idx}</td>
                <td class="loop-column">{entry['loop']}</td>
                <td class="test-column">{entry['test']}</td>
                <td class="item-column">{entry['item']}</td>
                <td class="testimg-column">{test_img_disp_html}</td>
                <td class="image-column">{image_html}</td>
            </tr>
"""
    
    html_content += """        </tbody>
    </table>
</body>
</html>
"""
    
    # Write HTML file
    output_path = os.path.join(test_folder, output_html)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"HTML report generated: {output_path}")
    return output_path

def main():
    if len(sys.argv) < 2:
        print("Usage: python tsum.py <test_folder> [output_file]")
        sys.exit(1)
    test_folder = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "summary.txt"
    output_path = os.path.join(test_folder, output_file)

    rows = []
    for loop_name in sorted(os.listdir(test_folder)):
        loop_path = os.path.join(test_folder, loop_name)
        if not os.path.isdir(loop_path):
            continue  # skip files like summary.txt
        print(f"Processing {loop_name}...")
        if loop_name.startswith("Loop_#"):
            loop_dir = loop_path
            log_file = find_log_file(loop_dir)
            if log_file:
                results = parse_log(log_file)
                rows.extend(results)

    # Sort rows by loop number if possible
    rows.sort(key=lambda x: x[0] if isinstance(x[0], int) else 9999)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("Loop, type, failed, passed, error, time (s), timeout\n")
        for row in rows:
            # Convert loop_num back to string for output
            out_row = [str(row[0])] + list(map(str, row[1:]))
            f.write(", ".join(out_row) + "\n")
    print(f"Summary written to {output_path}")
    
    # Generate HTML report for failed tests
    print("Generating HTML failure report...")
    generate_html_report(test_folder, "report.html")

if __name__ == "__main__":
    main()