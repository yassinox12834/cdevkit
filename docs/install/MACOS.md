# Install on macOS without the app

Every step the setup app does, as commands. Open **Terminal** (Cmd+Space, type `Terminal`) and run one block at a time.

## 1. Classic pack

### Apple's Command Line Tools (Git, Make, LLDB debugger)

```bash
xcode-select --install
```

A window opens: click **Install** and wait for it to finish.

### Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

It asks for your Mac password (nothing appears while you type, that is normal). Then put Homebrew on your PATH:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

On an Intel Mac, Homebrew is in `/usr/local` and already on PATH: skip these two lines.

### GCC, CMake, Ninja, Git, VS Code

```bash
brew install gcc cmake ninja git
brew install --cask visual-studio-code
```

### VS Code extensions

```bash
code --install-extension ms-vscode.cpptools
code --install-extension ms-vscode.cmake-tools
code --install-extension vadimcn.vscode-lldb
```

If `code` is not found: open VS Code, press Cmd+Shift+P and run **Shell Command: Install 'code' command in PATH**.

## 2. Important: `g++` on a Mac is not GCC

On macOS, `gcc` and `g++` are Apple Clang. Homebrew's GCC has a version number in its name:

```bash
ls $(brew --prefix)/bin | grep -E '^g(cc|\+\+)-[0-9]+$'
```

That prints something like `gcc-15` and `g++-15`. Use those names.

## 3. Check it works

```bash
g++-15 --version
cat > hello.cpp <<'EOF'
#include <iostream>
int main() { std::cout << "Hello from C++!\n"; }
EOF
g++-15 -std=c++20 -Wall hello.cpp -o hello
./hello
```

Replace `15` with the number from step 2. You should see `Hello from C++!`.

## 4. Optional packs

**Code quality**

```bash
brew install llvm cppcheck catch2 googletest
code --install-extension llvm-vs-code-extensions.vscode-clangd
code --install-extension usernamehw.errorlens
```

`llvm` gives clang-format, clang-tidy and clangd. Homebrew does not put them on PATH, so add this to `~/.zprofile`:

```bash
echo 'export PATH="$(brew --prefix llvm)/bin:$PATH"' >> ~/.zprofile
```

**GitHub in VS Code**

```bash
code --install-extension github.vscode-pull-request-github
code --install-extension github.vscode-github-actions
code --install-extension eamodio.gitlens
```

**Extras** (GitHub CLI, ccache, Doxygen, Google Benchmark)

```bash
brew install gh ccache doxygen google-benchmark
code --install-extension cschlosser.doxdocgen
code --install-extension ms-vscode.hexeditor
```

## 5. Configure Git and GitHub

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
git config --global core.autocrlf input
gh auth login
gh auth setup-git
```

## 6. Want the apps after all?

Python is not required: just start `setup.command`. If no Python is installed, it downloads a private copy into the kit's `.runtime` folder, without installing anything on the system.
