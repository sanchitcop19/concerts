#!/bin/sh
# Xcode Cloud runs this right after cloning the repo. The Xcode project isn't committed
# (it's generated from ios/project.yml), so create it here before Xcode Cloud builds.
set -e
brew install xcodegen
cd "$CI_PRIMARY_REPOSITORY_PATH/ios"
xcodegen generate
