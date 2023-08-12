# Nelson Dane
# Script to Update or Initialize Project

import os
import subprocess
import sys


def update_project(branch=None):
    # Check if git is installed
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, check=True)
    except FileNotFoundError:
        print("Git is not installed, please install Git so the project can auto update. Exiting...")
        sys.exit(1)
    # Check if .git folder exists
    project_dir = os.path.dirname(os.path.realpath(__file__))
    if os.path.exists(os.path.join(project_dir, ".git")):
        # Get current branch
        if branch is None:
            branch = (
                subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
                .decode("utf-8")
                .strip()
            )
        else:
            branch = branch.strip()
            subprocess.run(["git", "checkout", branch], cwd=project_dir, check=True)
        print(f"Current branch: {branch}")
        # Update the project
        print("Updating project...")
        subprocess.run(["git", "pull", "origin", branch], cwd=project_dir, check=True)
        print("Update completed!")
    else:
        # Clone the repository
        print("Cloning repository...")
        repo_url = "https://github.com/NelsonDane/auto-rsa"
        subprocess.run(["git", "clone", repo_url, f"{project_dir}/temp"], check=True)

        # Move .git folder to initialize repository
        print("Moving .git folder...")
        subprocess.run(["mv", f"{project_dir}/temp/.git", project_dir], check=True)
        subprocess.run(["rm", "-rf", f"{project_dir}/temp"], check=True)
        print("Repository initialized!")
        # Update the project
        update_project(branch)


if __name__ == "__main__":
    branchIn = None
    if len(sys.argv) > 1:
        branchIn = sys.argv[1]
    update_project(branchIn)
