# Template Build System

This document describes the template build system for What's Now Playing templates, which allows for
maintainable and consistent template generation from modular components.

## Overview

The template build system generates all `.htm` template files from modular source components,
making future updates and maintenance much easier. Instead of manually editing dozens of
individual template files, you can modify shared components and regenerate all templates consistently.

## Directory Structure

```none
template-src/
├── bases/                          # Jinja2 base templates
│   ├── websocket-base.jinja2       # Base for WebSocket templates
│   └── static-base.jinja2          # Base for static templates
├── components/                     # Reusable components
│   ├── css/                        # CSS components
│   │   ├── obs-compatibility.css   # OBS browser source compatibility
│   │   ├── mtv-layout.css          # MTV-style layout
│   │   ├── basic-text.css          # Basic text styling
│   │   └── ...
│   ├── js/                         # JavaScript components
│   │   ├── single-image-display.js # Single image display logic
│   │   ├── mtv-display.js          # MTV-style display logic
│   │   ├── fade-effects.js         # Fade in/out effects
│   │   └── ...
│   ├── html/                       # HTML layout components
│   │   ├── basic-text-layout.html  # Basic text container
│   │   ├── mtv-layout.html         # MTV-style layout
│   │   └── ...
│   └── websocket/                  # WebSocket-specific components
│       ├── metadata-streaming.js   # WebSocket metadata streaming
│       └── ...
├── configs/                        # YAML configuration files
│   ├── basic-templates.yaml        # Basic text templates
│   ├── mtv-templates.yaml          # MTV-style templates
│   ├── artist-templates.yaml       # Artist image templates
│   └── ...
└── vendor/                         # Vendor libraries (optional)
    └── jquery.min.js               # Local jQuery copy
```

## Build Script

The `build_templates.py` script generates all templates from the source components.

### Usage

```bash
# Build all template families
python build_templates.py

# Build a specific family
python build_templates.py --family basic_text

# Build with vendor file copying
python build_templates.py  # Automatically copies vendor files
```

### Available Families

- `basic_text` - Simple colored text templates
- `mtv_style` - MTV-style layouts with/without covers
- `artist_images` - Artist logos, banners, thumbs, covers
- `artist_fanart` - Artist fanart images
- `complex_websocket` - Complex templates like coverslideshow
- `static_web` - Basic static web templates
- `static_mtv` - Non-WebSocket MTV templates
- `explode_effects` - Templates with explode animations
- `slide_effects` - Templates with slide animations
- `gifwords` - GIF word templates
- `special_layouts` - Special templates like requests

## Configuration Format

Templates are defined in YAML configuration files in `template-src/configs/`. Each file defines template families:

```yaml
template_families:
  basic_text:
    base: websocket-base                    # Base template to use
    description: "Basic text templates"
    common_css:                             # CSS applied to all templates
      - obs-compatibility
      - basic-text
    common_websocket:                       # WebSocket components for all
      - metadata-streaming

    templates:
      ws-basicblack:
        title: "Titlecard"
        description: "Basic black text template"
        body_layout: basic-text-layout      # HTML layout component
        display_js: basic-text-display      # JavaScript display logic
        color: "black"                      # Template-specific color

      ws-basicblue:
        title: "Titlecard"
        description: "Basic blue text template"
        body_layout: basic-text-layout
        display_js: basic-text-display
        color: "blue"
```

### Configuration Options

#### Family-Level Options

- `base` - Base template (`websocket-base` or `static-base`)
- `description` - Human-readable description
- `common_css` - CSS components applied to all templates in family
- `common_websocket` - WebSocket components for all templates
- `external_css` - External CSS URLs
- `external_js` - External JavaScript URLs
- `font_link` - Google Fonts or other font URLs

#### Template-Level Options

- `title` - HTML page title
- `description` - Template description
- `body_layout` - HTML layout component name
- `display_js` - JavaScript display logic component
- `custom_css` - Template-specific CSS components
- `effects` - JavaScript effect components (fade, explode, etc.)
- `color` - Inline color CSS
- `image_field` - Which image field to display (coverimage, artistlogo, etc.)
- `refresh_rate` - Meta refresh rate for static templates

## Base Templates

### websocket-base.jinja2

Used for WebSocket templates that connect to the What's Now Playing WebSocket streams:

```html
<!DOCTYPE HTML>
<html>
<head>
    <meta charset="utf-8">
    <title>{{template_title}}</title>
    {%- if font_link %}
    <link href="{{font_link}}" rel="stylesheet" type="text/css" />
    {%- endif %}
    {%- if external_imports %}
    {{external_imports}}
    {%- endif %}
    <style>
        {{css_content}}
    </style>
    <script src="https://code.jquery.com/jquery-3.6.1.js"></script>
    <script src="/nowplaying-websocket.js"></script>
</head>
<body>
    {{body_content}}
    <script type="text/javascript">
        {{js_content}}
    </script>
</body>
</html>
```

### static-base.jinja2

Used for static templates that refresh periodically:

```html
<!DOCTYPE HTML>
<html>
<head>
    <meta charset="utf-8">
    <title>{{template_title}}</title>
    {%- if font_link %}
    <link href="{{font_link}}" rel="stylesheet" type="text/css" />
    {%- endif %}
    {%- if external_imports %}
    {{external_imports}}
    {%- endif %}
    <style>
        {{css_content}}
    </style>
    {%- if refresh_rate %}
    <meta http-equiv="refresh" content="{{refresh_rate}}">
    {%- endif %}
</head>
<body>
    {{body_content}}
    {%- if js_content %}
    <script type="text/javascript">
        {{js_content}}
    </script>
    {%- endif %}
</body>
</html>
```

## Component System

### CSS Components

Reusable CSS files that can be mixed and matched:

- `obs-compatibility.css` - Ensures templates work in OBS browser sources
- `basic-text.css` - Basic text styling
- `mtv-layout.css` - MTV-style layout with cover images
- Template-specific CSS files for unique styling

### JavaScript Components

Modular JavaScript functionality:

- `single-image-display.js` - Display single images (covers, logos, etc.)
- `mtv-display.js` - MTV-style display with text and cover
- `fade-effects.js` - Fade in/out animations
- `explode-effects.js` - jQuery UI explode effects
- `slide-effects.js` - Slide up/down animations

### HTML Components

Reusable HTML layout structures:

- `basic-text-layout.html` - Simple title/artist text container
- `mtv-layout.html` - MTV-style layout with image and text sections
- `coverslideshow-layout.html` - Complex slideshow container

### WebSocket Components

WebSocket-specific functionality for real-time templates:

- `metadata-streaming.js` - Standard WebSocket metadata streaming setup
- Session tracking and OBS integration via nowplaying-websocket.js library

## Vendor File Management

The build system automatically downloads and manages external libraries:

### Configuration-Based Downloads

Vendor dependencies are defined in `template-src/vendor.yaml`:

```yaml
vendor_dependencies:
  jquery.min.js:
    url: "https://code.jquery.com/jquery-3.6.1.min.js"
    version: "3.6.1"
    description: "jQuery JavaScript library"

  anime.min.js:
    url: "https://cdn.jsdelivr.net/npm/animejs@4.1.1/lib/anime.iife.min.js"
    version: "4.1.1"
    description: "Anime.js animation library (IIFE version)"
```

### Automatic Download Process

1. **First build**: Downloads files from URLs to `template-src/vendor/` (cache)
2. **Subsequent builds**: Uses cached files, no re-download needed
3. **Output**: Copies cached files to `nowplaying/templates/vendor/`

### Using Vendor Files in Templates

Reference vendor files in template configurations:

```yaml
external_js:
  - "vendor/jquery.min.js"     # Local jQuery
  - "vendor/anime.min.js"      # Local anime.js
```

### Benefits

- **Clean source tree**: No large binary files in Git
- **Version control**: Exact versions specified in configuration
- **Reliable builds**: No internet dependency after initial download
- **Easy updates**: Change URL in config, delete cache file, rebuild

## Adding New Templates

### 1. Create Components

Add any new CSS, JavaScript, or HTML components to the appropriate `components/` subdirectories.

### 2. Update Configuration

Add your template to an existing family or create a new family in a YAML config file:

```yaml
my_new_template:
  title: "My Template"
  description: "Custom template description"
  body_layout: my-layout
  display_js: my-display-logic
  custom_css: [my-styles]
```

### 3. Build Templates

Run the build script to generate the new template:

```bash
python build_templates.py --family my_family
```

## Advanced Features

### Template Variable Substitution

The build system can customize JavaScript based on template configuration:

```javascript
// In component file:
function getImageField() {
    return 'coverimage'; // Default, overridden by specific templates
}

// Gets replaced with:
function getImageField() {
    return 'artistlogo'; // Artist Logo Template
}
```

### Conditional Content

Base templates use Jinja2 conditional blocks to include content only when needed:

```jinja2
{%- if font_link %}
<link href="{{font_link}}" rel="stylesheet" type="text/css" />
{%- endif %}
```

The `{%-` syntax strips whitespace when conditions are false, preventing empty lines.

### Effect Stacking

Templates can combine multiple effects:

```yaml
effects:
  - fade-effects
  - slide-effects
```

## Best Practices

### Component Design

- Keep components focused on single responsibilities
- Use descriptive filenames that indicate purpose
- Include comments in CSS and JavaScript components
- Test components across different template types

### Configuration Management

- Group related templates into logical families
- Use consistent naming conventions
- Document template purposes in descriptions
- Validate YAML syntax before building

### Build Workflow

- Always build templates after component changes
- Test generated templates in both browsers and OBS
- Commit both source components and generated templates
- Use specific family builds during development for speed

### Maintenance

- Regularly review and consolidate similar components
- Update vendor files when new versions are available
- Keep documentation current with system changes
- Monitor template performance in production use

## Troubleshooting

### Build Errors

- **Component not found**: Check file paths and naming in component directories
- **YAML syntax error**: Validate YAML syntax in configuration files
- **Template rendering error**: Check Jinja2 syntax in base templates

### Generated Template Issues

- **Extra whitespace**: Ensure Jinja2 conditional blocks use `{%-` syntax
- **Missing functionality**: Verify component files exist and are properly referenced
- **JavaScript errors**: Check console for syntax errors in generated scripts

### Performance Issues

- **Slow builds**: Build specific families during development instead of all families
- **Large templates**: Review component size and consider splitting large JavaScript files
- **Browser compatibility**: Test generated templates across different browsers and OBS versions

This build system provides a maintainable foundation for the What's Now Playing template ecosystem,
making future updates and customizations much more manageable.
