#!/bin/bash
# Build Android APK from PWA using Bubblewrap
# Usage: ./scripts/build-apk.sh [host] [version]
# Example: ./scripts/build-apk.sh myserver.com 1.0.0

set -e

HOST="${1:-example.com}"
VERSION="${2:-1.0.0}"
VERSION_CODE=$(date +%Y%m%d)

# Strip protocol if provided
HOST=$(echo "$HOST" | sed 's|https://||' | sed 's|http://||' | sed 's|/$||')

echo "🤖 Building APK for PatreonReader"
echo "   Host: $HOST"
echo "   Version: $VERSION"
echo ""

# Check dependencies
command -v node >/dev/null 2>&1 || { echo "❌ Node.js is required. Install from https://nodejs.org"; exit 1; }
command -v java >/dev/null 2>&1 || { echo "❌ Java JDK is required. Install JDK 17+"; exit 1; }

# Install bubblewrap if not present
if ! command -v bubblewrap &> /dev/null; then
    echo "📦 Installing Bubblewrap..."
    npm install -g @bubblewrap/cli
fi

# Check for Android SDK
if [ -z "$ANDROID_HOME" ] && [ -z "$ANDROID_SDK_ROOT" ]; then
    echo "⚠️  ANDROID_HOME not set. Bubblewrap will prompt for SDK installation."
fi

# Create build directory
BUILD_DIR="build/android"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Copy and update manifest
cp ../../twa-manifest.json ./twa-manifest.json

# Update manifest with parameters
if command -v jq &> /dev/null; then
    jq --arg host "$HOST" \
       --arg version "$VERSION" \
       --argjson versionCode "$VERSION_CODE" \
       --arg startUrl "https://$HOST/" \
       --arg iconUrl "https://$HOST/static/icons/icon-512.png" \
       --arg manifestUrl "https://$HOST/manifest.json" \
       --arg fullScopeUrl "https://$HOST/" \
       '.host = $host | .appVersionName = $version | .appVersionCode = $versionCode | .startUrl = $startUrl | .iconUrl = $iconUrl | .maskableIconUrl = $iconUrl | .webManifestUrl = $manifestUrl | .fullScopeUrl = $fullScopeUrl' \
       twa-manifest.json > twa-manifest-updated.json
    mv twa-manifest-updated.json twa-manifest.json
else
    # Fallback: use sed if jq not available
    sed -i.bak "s/\"host\": \"[^\"]*\"/\"host\": \"$HOST\"/" twa-manifest.json
    sed -i.bak "s/\"appVersionName\": \"[^\"]*\"/\"appVersionName\": \"$VERSION\"/" twa-manifest.json
    sed -i.bak "s/\"appVersionCode\": [0-9]*/\"appVersionCode\": $VERSION_CODE/" twa-manifest.json
    rm -f twa-manifest.json.bak
fi

echo "📋 Manifest configured:"
cat twa-manifest.json

# Generate keystore if not exists
KEYSTORE="android.keystore"
if [ ! -f "$KEYSTORE" ]; then
    echo ""
    echo "🔑 Generating signing key..."
    keytool -genkeypair \
        -alias patreonreader \
        -keyalg RSA \
        -keysize 2048 \
        -validity 10000 \
        -keystore "$KEYSTORE" \
        -storepass android \
        -keypass android \
        -dname "CN=Patreon Reader, OU=Development, O=Ecleptic, L=Unknown, ST=Unknown, C=US"
fi

# Initialize and build
echo ""
echo "🔧 Initializing Bubblewrap project..."
export BUBBLEWRAP_KEYSTORE_PASSWORD="${KEYSTORE_PASSWORD:-android}"
export BUBBLEWRAP_KEY_PASSWORD="${KEYSTORE_PASSWORD:-android}"

bubblewrap init --manifest twa-manifest.json --skipPwaValidation

echo ""
echo "🏗️  Building APK..."
bubblewrap build --skipPwaValidation

# Move APK to output
OUTPUT_NAME="PatreonReader-v${VERSION}.apk"
if [ -f "app-release-signed.apk" ]; then
    mv app-release-signed.apk "../../$OUTPUT_NAME"
elif [ -f "app-release-unsigned.apk" ]; then
    mv app-release-unsigned.apk "../../$OUTPUT_NAME"
else
    echo "❌ APK not found!"
    exit 1
fi

cd ../..

echo ""
echo "✅ APK built successfully!"
echo "📦 Output: $OUTPUT_NAME"
echo ""
echo "To install on Android:"
echo "  adb install $OUTPUT_NAME"
echo ""
echo "Or transfer to your device and install manually."
