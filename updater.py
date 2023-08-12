# Nelson Dane
# Script to Update or Initialize Project

import os
import platform
import shutil
import stat
import subprocess
import sys


def delete_temp(path):
    # Loop through all files and folders in temp and set permissions to allow deletion
    for root, dirs, files in os.walk(path):
        for d in dirs:
            os.chmod(os.path.join(root, d), stat.S_IWRITE)
        for f in files:
            os.chmod(os.path.join(root, f), stat.S_IWRITE)
    shutil.rmtree(os.path.join(path))


def update_project(branch=None):
    try:
        # Check if git is installed
        try:
            subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, check=True)
        except FileNotFoundError:
            print("Git is not installed, please install so the project can auto update")
            return
        # Get current OS
        WINDOWS = True if platform.system() == "Windows" else False
        if WINDOWS:
            print("Running on Windows")
        # Check if .git folder exists
        project_dir = os.path.dirname(os.path.realpath(__file__))
        if os.path.exists(os.path.join(project_dir, ".git")):
            # Get current branch
            if branch is None:
                branch = (
                    subprocess.check_output(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"]
                    )
                    .decode("utf-8")
                    .strip()
                )
            else:
                branch = branch.strip()
                subprocess.run(["git", "stash"], cwd=project_dir, check=True)
                subprocess.run(["git", "checkout", branch], cwd=project_dir, check=True)
            print(f"Current branch: {branch}")
            # Update the project
            print("Updating project...")
            subprocess.run(
                ["git", "pull", "origin", branch], cwd=project_dir, check=True
            )
            print("Update completed!")
        else:
            # Check if project directory exists and is empty, remove if not
            if os.path.exists(os.path.join(project_dir, "temp")):
                delete_temp(os.path.join(project_dir, "temp"))
            # Clone the repository
            print("Cloning repository...")
            repo_url = "https://github.com/NelsonDane/auto-rsa"
            subprocess.run(
                ["git", "clone", repo_url, f"{project_dir}/temp"], check=True
            )

            # Move .git folder to initialize repository and remove temp folder
            print("Moving .git folder...")
            shutil.move(f"{project_dir}/temp/.git", project_dir)
            delete_temp(os.path.join(project_dir, "temp"))
            print("Repository initialized!")
            # Update the project
            update_project(branch)
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        print("Project update failed!")
        return


if __name__ == "__main__":
    branchIn = None
    if len(sys.argv) > 1:
        branchIn = sys.argv[1]
    update_project(branchIn)
