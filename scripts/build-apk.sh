#!/bin/bash
# Build Android APK from TWA project using Gradle (CI-compatible)
# Usage: ./scripts/build-apk.sh [host] [version]
# Example: ./scripts/build-apk.sh myserver.com 1.0.0
#
# Prerequisites:
#   - Android project must already exist in build/android/ (run bubblewrap init locally first)
#   - Java JDK 17+ installed
#
# Environment variables:
#   KEYSTORE_PASSWORD - Password for the signing keystore (default: android)
#   KEYSTORE_PATH - Path to keystore file (default: build/android/android.keystore)

set -e

HOST="${1:-example.com}"
VERSION="${2:-1.0.0}"
VERSION_CODE=$(date +%Y%m%d)

# Strip protocol if provided
HOST=$(echo "$HOST" | sed 's|https://||' | sed 's|http://||' | sed 's|/$||')

echo "🤖 Building APK for PatreonReader"
echo "   Host: $HOST"
echo "   Version: $VERSION"
echo "   Version Code: $VERSION_CODE"
echo ""

# =============================================================================
# Configuration
# =============================================================================
KEYSTORE_PASSWORD="${KEYSTORE_PASSWORD:-android}"
KEY_PASSWORD="${KEY_PASSWORD:-$KEYSTORE_PASSWORD}"
KEY_ALIAS="${KEY_ALIAS:-patreonreader}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build/android"
KEYSTORE_PATH="${KEYSTORE_PATH:-$BUILD_DIR/android.keystore}"

# Use bubblewrap's JDK if available (Gradle requires JDK 17-21, not 25+)
BUBBLEWRAP_JDK="$HOME/.bubblewrap/jdk"
if [ -d "$BUBBLEWRAP_JDK" ]; then
    # Find JDK directory - handle both macOS bundle and standard layouts
    JDK_DIR=$(find "$BUBBLEWRAP_JDK" -maxdepth 1 -type d -name "jdk-*" | head -1)
    if [ -n "$JDK_DIR" ]; then
        # macOS JDK bundles have Contents/Home structure
        if [ -d "$JDK_DIR/Contents/Home" ]; then
            export JAVA_HOME="$JDK_DIR/Contents/Home"
        else
            export JAVA_HOME="$JDK_DIR"
        fi
        export PATH="$JAVA_HOME/bin:$PATH"
    fi
fi

# Use bubblewrap's Android SDK if available
BUBBLEWRAP_SDK="$HOME/.bubblewrap/android_sdk"
if [ -d "$BUBBLEWRAP_SDK" ]; then
    export ANDROID_HOME="$BUBBLEWRAP_SDK"
    export ANDROID_SDK_ROOT="$BUBBLEWRAP_SDK"
    export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/tools:$PATH"
fi

# =============================================================================
# Dependency Checks
# =============================================================================
check_dependencies() {
    echo "🔍 Checking dependencies..."
    
    if ! command -v java &> /dev/null; then
        echo "❌ Java JDK is required. Install JDK 17+"
        exit 1
    fi
    JAVA_VER=$(java -version 2>&1 | head -1)
    echo "   ✓ Java $JAVA_VER"
    [ -n "$JAVA_HOME" ] && echo "   ✓ JAVA_HOME=$JAVA_HOME"
    [ -n "$ANDROID_HOME" ] && echo "   ✓ ANDROID_HOME=$ANDROID_HOME"
    
    if [ ! -d "$BUILD_DIR/app" ]; then
        echo "❌ Android project not found at $BUILD_DIR"
        echo "   Run 'bubblewrap init' locally first to generate the project"
        exit 1
    fi
    echo "   ✓ Android project found"
    
    if [ ! -f "$KEYSTORE_PATH" ]; then
        echo "⚠️  Keystore not found, will generate one"
    else
        echo "   ✓ Keystore found"
    fi
    echo ""
}

# =============================================================================
# Update TWA Manifest and Android config
# =============================================================================
update_manifest() {
    echo "📋 Updating manifest for $HOST..."
    cd "$BUILD_DIR"
    
    if command -v jq &> /dev/null; then
        jq --arg host "$HOST" \
           --arg version "$VERSION" \
           --argjson versionCode "$VERSION_CODE" \
           --arg startUrl "https://$HOST/" \
           --arg iconUrl "https://$HOST/static/icons/icon-512.png" \
           --arg manifestUrl "https://$HOST/manifest.json" \
           --arg fullScopeUrl "https://$HOST/" \
           '.host = $host | .appVersionName = $version | .appVersionCode = $versionCode | .startUrl = $startUrl | .iconUrl = $iconUrl | .maskableIconUrl = $iconUrl | .webManifestUrl = $manifestUrl | .fullScopeUrl = $fullScopeUrl | .appVersion = $version' \
           twa-manifest.json > twa-manifest-updated.json
        mv twa-manifest-updated.json twa-manifest.json
    else
        sed -i.bak "s|\"host\": \"[^\"]*\"|\"host\": \"$HOST\"|g" twa-manifest.json
        sed -i.bak "s|\"appVersionName\": \"[^\"]*\"|\"appVersionName\": \"$VERSION\"|g" twa-manifest.json
        sed -i.bak "s|\"appVersion\": \"[^\"]*\"|\"appVersion\": \"$VERSION\"|g" twa-manifest.json
        sed -i.bak "s|\"appVersionCode\": [0-9]*|\"appVersionCode\": $VERSION_CODE|g" twa-manifest.json
        rm -f twa-manifest.json.bak
    fi
    
    # Update app/build.gradle with version info
    if [ -f "app/build.gradle" ]; then
        sed -i.bak "s|versionCode [0-9]*|versionCode $VERSION_CODE|g" app/build.gradle
        sed -i.bak "s|versionName \"[^\"]*\"|versionName \"$VERSION\"|g" app/build.gradle
        rm -f app/build.gradle.bak
    fi
    
    echo "   ✓ Manifest updated"
}

# =============================================================================
# Generate Keystore if needed
# =============================================================================
generate_keystore() {
    if [ ! -f "$KEYSTORE_PATH" ]; then
        echo "🔑 Generating signing key..."
        keytool -genkeypair \
            -alias android \
            -keyalg RSA \
            -keysize 2048 \
            -validity 10000 \
            -keystore "$KEYSTORE_PATH" \
            -storepass "$KEYSTORE_PASSWORD" \
            -keypass "$KEY_PASSWORD" \
            -dname "CN=Patreon Reader, OU=Development, O=Ecleptic, L=Unknown, ST=Unknown, C=US"
        echo "   ✓ Keystore generated"
    fi
}

# =============================================================================
# Build with Gradle (CI-compatible, non-interactive)
# =============================================================================
build_apk() {
    echo ""
    echo "🔧 Building with Gradle..."
    cd "$BUILD_DIR"
    
    # Make gradlew executable
    chmod +x ./gradlew
    
    # Build release APK
    echo "   Running assembleRelease..."
    ./gradlew assembleRelease \
        -Pandroid.injected.signing.store.file="$KEYSTORE_PATH" \
        -Pandroid.injected.signing.store.password="$KEYSTORE_PASSWORD" \
        -Pandroid.injected.signing.key.alias="$KEY_ALIAS" \
        -Pandroid.injected.signing.key.password="$KEY_PASSWORD" \
        --no-daemon \
        --console=plain \
        2>&1 | tee build.log
    
    # Also build AAB for Play Store
    echo ""
    echo "   Running bundleRelease..."
    ./gradlew bundleRelease \
        -Pandroid.injected.signing.store.file="$KEYSTORE_PATH" \
        -Pandroid.injected.signing.store.password="$KEYSTORE_PASSWORD" \
        -Pandroid.injected.signing.key.alias="$KEY_ALIAS" \
        -Pandroid.injected.signing.key.password="$KEY_PASSWORD" \
        --no-daemon \
        --console=plain \
        2>&1 | tee -a build.log
    
    echo "   ✓ Build complete"
}

# =============================================================================
# Collect Output
# =============================================================================
collect_output() {
    OUTPUT_NAME="PatreonReader-v${VERSION}.apk"
    AAB_NAME="PatreonReader-v${VERSION}.aab"
    
    echo ""
    echo "📦 Collecting build artifacts..."
    
    # Find and copy the signed APK
    APK_PATH=$(find "$BUILD_DIR/app/build/outputs/apk/release" -name "*.apk" 2>/dev/null | head -1)
    if [ -n "$APK_PATH" ] && [ -f "$APK_PATH" ]; then
        cp "$APK_PATH" "$PROJECT_DIR/$OUTPUT_NAME"
        echo "   ✓ Signed APK: $OUTPUT_NAME"
    fi
    
    # Find and copy the AAB
    AAB_PATH=$(find "$BUILD_DIR/app/build/outputs/bundle/release" -name "*.aab" 2>/dev/null | head -1)
    if [ -n "$AAB_PATH" ] && [ -f "$AAB_PATH" ]; then
        cp "$AAB_PATH" "$PROJECT_DIR/$AAB_NAME"
        echo "   ✓ App Bundle: $AAB_NAME"
    fi
    
    cd "$PROJECT_DIR"
    
    if [ ! -f "$OUTPUT_NAME" ] && [ ! -f "$AAB_NAME" ]; then
        echo "❌ No APK or AAB found!"
        echo "   Check $BUILD_DIR/build.log for details"
        exit 1
    fi
    
    echo ""
    echo "✅ Build successful!"
    [ -f "$OUTPUT_NAME" ] && echo "   APK: $OUTPUT_NAME ($(du -h "$OUTPUT_NAME" | cut -f1))"
    [ -f "$AAB_NAME" ] && echo "   AAB: $AAB_NAME ($(du -h "$AAB_NAME" | cut -f1))"
    echo ""
    echo "To install on Android:"
    echo "  adb install $OUTPUT_NAME"
}

# =============================================================================
# Main
# =============================================================================
main() {
    check_dependencies
    update_manifest
    generate_keystore
    build_apk
    collect_output
}

main
