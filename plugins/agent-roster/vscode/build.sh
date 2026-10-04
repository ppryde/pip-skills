#!/bin/sh
# Packs the helper into a .vsix (a zip with a manifest) with no npm tooling,
# then installs it: `sh build.sh install`.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
version=$(sed -n 's/.*"version": "\(.*\)".*/\1/p' "$here/package.json")
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

mkdir "$stage/extension"
cp "$here/package.json" "$here/extension.js" "$stage/extension/"
cat > "$stage/[Content_Types].xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension=".json" ContentType="application/json"/><Default Extension=".js" ContentType="application/javascript"/><Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>
XML
cat > "$stage/extension.vsixmanifest" <<XML
<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="agent-roster-vscode" Version="$version" Publisher="pip" />
    <DisplayName>agent-roster helper</DisplayName>
    <Description xml:space="preserve">Opens a terminal tab attached to a tmux session for the agent-roster mod.</Description>
    <Categories>Other</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.80.0" />
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" /></Installation>
  <Dependencies />
  <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" /></Assets>
</PackageManifest>
XML

out="$here/agent-roster-vscode-$version.vsix"
rm -f "$out"
(cd "$stage" && zip -qr "$out" '[Content_Types].xml' extension.vsixmanifest extension)
echo "$out"
if [ "${1:-}" = install ]; then code --install-extension "$out" --force; fi
