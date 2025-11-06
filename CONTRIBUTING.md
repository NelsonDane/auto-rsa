# Contributing

Thanks for wanting to contribute to the project! Here are some steps to get you setup for contributing:

1. Upon cloning the repository, install the git submodules with:

    ```bash
    git submodule update --init --recursive
    ```
2. This project is setup to use [uv](https://github.com/astral-sh/uv) for managing Python versions, packages, linting, and more! Install this, it's awesome!
3. Install dependencies with `uv sync`.
4. If using `VSCode`, install the recommended extensions:

    4.1. Go to the Extensions tab
    4.2. Click the Funnel icon in the search bar
    4.3. Select "Recommended"
    4.4. Press the Cloud icon with the Down Arrow to install all recommended extensions
5. This project uses a few tools for linting and type checking:
-  [Ruff](https://github.com/astral-sh/ruff) for linting and formatting. You can run `ruff check` to check for linting errors, and `ruff format --check` to format your files with the correct line-endings.
- [Mypy](http://mypy-lang.org/) for type checking. You can run `mypy .` to check for type errors.

Note: Both of these have VSCode extensions that you should've installed in step 4, so you'll get type hints and feedback as you work!

6. When you're ready to contribute, create a new branch off of `main` for your changes. Make sure to write clear commit messages and follow any coding style guidelines used in the project.
7. I have lots of GitHub Actions set up to automatically check for linting and type errors on pull requests, so make sure to address any issues that those find. If you'd like to run those locally, you can use [Act](https://github.com/nektos/act).
- `act -j lint` to run the linter
- `act -j mypy` to run the type checker
8. This project also has Docker support. Make sure that the Docker image still builds by running `docker build -t rsa .` before submitting your pull request.
9. Finally, submit your pull request! Make sure to describe the changes you've made and why they are important. I'll review it as soon as I can!
