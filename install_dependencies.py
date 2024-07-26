import subprocess
import sys
import re
import os

def get_installed_webull_commit_hash():
    try:
        # Assuming webull is installed in the site-packages directory
        from webull import __file__ as webull_file
        webull_path = os.path.dirname(webull_file)
        git_head_path = os.path.join(webull_path, '..', '.git', 'HEAD')

        if os.path.isfile(git_head_path):
            with open(git_head_path, 'r') as head_file:
                ref = head_file.read().strip()
                if ref.startswith('ref:'):
                    ref_path = os.path.join(webull_path, '..', '.git', ref.split(' ')[1])
                    with open(ref_path, 'r') as ref_file:
                        return ref_file.read().strip()
                else:
                    return ref
        return None
    except Exception as e:
        print(f"Error checking installed webull commit hash: {e}")
        return None

def get_webull_commit_hash_from_requirements(requirements_file):
    with open(requirements_file, 'r') as file:
        for line in file:
            if line.startswith('-e git+https://github.com/NelsonDane/webull.git'):
                match = re.search(r'@([a-f0-9]+)#egg=webull', line)
                if match:
                    return match.group(1)
    return None

def install_dependencies(requirements_file, exclude_webull=False):
    with open(requirements_file, 'r') as file:
        requirements = file.readlines()
    
    if exclude_webull:
        requirements = [line for line in requirements if 'webull' not in line]
    
    for requirement in requirements:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', requirement.strip()])

def main():
    requirements_file = 'requirements.txt'
    installed_commit_hash = get_installed_webull_commit_hash()
    required_commit_hash = get_webull_commit_hash_from_requirements(requirements_file)

    print(f"Installed commit hash: {installed_commit_hash}")
    print(f"Required commit hash: {required_commit_hash}")

    if installed_commit_hash == required_commit_hash:
        print("Webull is already installed and up-to-date.")
        install_dependencies(requirements_file, exclude_webull=True)
    else:
        install_dependencies(requirements_file, exclude_webull=False)

if __name__ == "__main__":
    main()