# MkDocs Multi-Version Deployment

This project now uses MkDocs Material with multi-version support via the `mike` plugin.

## Local Development

```bash
# Install dependencies
pip install -r requirements-mkdocs.txt

# Serve locally
mkdocs serve

# Build static site
mkdocs build
```

## Multi-Version Deployment

### Initial Setup

```bash
# Deploy current version as latest
mike deploy --push --update-aliases v4.2 latest

# Set default version
mike set-default --push latest
```

### Adding New Versions

```bash
# Deploy new version
mike deploy --push --update-aliases v4.3 latest

# Update default if needed
mike set-default --push latest
```

### Version Management

```bash
# List all versions
mike list

# Delete a version
mike delete --push v4.1

# Serve all versions locally
mike serve
```

## GitHub Actions Integration

Add to `.github/workflows/docs.yml`:

```yaml
name: Deploy Documentation

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: 3.x

      - name: Install dependencies
        run: pip install -r requirements-mkdocs.txt

      - name: Deploy docs
        run: |
          git config user.name github-actions
          git config user.email github-actions@github.com

          if [[ $GITHUB_REF == refs/tags/* ]]; then
            VERSION=${GITHUB_REF#refs/tags/}
            mike deploy --push --update-aliases $VERSION latest
          else
            mike deploy --push dev
          fi
```

## Site Structure

- Latest stable: `https://docs.whatsnowplaying.com/`
- Specific version: `https://docs.whatsnowplaying.com/v4.2/`
- Development: `https://docs.whatsnowplaying.com/dev/`

## Migration Notes

- All RST files have been converted to Markdown
- Sphinx-specific files removed (conf.py, requirements.txt, etc.)
- Image paths preserved
- Navigation structure maintained
- Multi-version support added via mike plugin
