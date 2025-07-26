#!/usr/bin/env python3
"""Template Builder for What's Now Playing Templates"""

import urllib.request
from pathlib import Path
from typing import Any

import jinja2
import yaml


class TemplateBuilder:
    """Template builder for What's Now Playing templates with component system"""

    def __init__(
        self, src_dir: str = "template-src", output_dir: str = "nowplaying/templates"
    ) -> None:
        self.src_dir = Path(src_dir)
        self.output_dir = Path(output_dir)
        self.jinja_env = jinja2.Environment(loader=jinja2.FileSystemLoader(self.src_dir / "bases"))

    def load_component(self, component_type: str, component_name: str) -> str:
        """Load a component file (CSS, JS, HTML) with source comment"""
        component_file = (
            self.src_dir
            / "components"
            / component_type
            / f"{component_name}.{component_type.rstrip('s')}"
        )

        # Find the actual file that exists
        actual_file = None
        if component_file.exists():
            actual_file = component_file
        else:
            # Try alternative extensions
            for ext in ["css", "js", "html"]:
                alt_file = self.src_dir / "components" / component_type / f"{component_name}.{ext}"
                if alt_file.exists():
                    actual_file = alt_file
                    break

        if actual_file:
            content = actual_file.read_text()
            relative_path = actual_file.relative_to(self.src_dir)

            # Add source comment based on file type
            if component_type == "css":
                return f"/* {relative_path} */\n{content}"
            if component_type in {"js", "websocket"}:
                return f"// {relative_path}\n{content}"
            if component_type == "html":
                return f"<!-- {relative_path} -->\n{content}"
            return content

        print(f"Warning: Component not found: {component_type}/{component_name}")
        return ""

    def _gather_css_content(
        self, family_config: dict[str, Any], template_config: dict[str, Any]
    ) -> list[str]:
        """Gather all CSS content for a template"""
        css_parts = []

        # Add common family CSS
        for css_name in family_config.get("common_css", []):
            if css_content := self.load_component("css", css_name):
                css_parts.append(css_content)

        # Add template-specific CSS (replaces common CSS)
        if template_config.get("css"):
            if css_content := self.load_component("css", template_config["css"]):
                css_parts.append(css_content)

        # Add template-specific custom CSS
        for css_name in template_config.get("custom_css", []):
            if css_content := self.load_component("css", css_name):
                css_parts.append(css_content)

        # Add color-specific CSS if specified
        if template_config.get("color"):
            color_css = f".container {{ color: {template_config['color']}; }}"
            css_parts.append(color_css)

        return css_parts

    def _gather_js_content(
        self, family_config: dict[str, Any], template_config: dict[str, Any]
    ) -> list[str]:
        """Gather all JavaScript content for a template"""
        js_parts = []

        # Add display JavaScript
        if template_config.get("display_js"):
            if display_js := self.load_component("js", template_config["display_js"]):
                # Customize image field if specified
                if template_config.get("image_field"):
                    old_func = (
                        "function getImageField() {\n    return 'coverimage'; "
                        "// Default, overridden by specific templates\n}"
                    )
                    new_func = (
                        f"function getImageField() {{\n    return '{template_config['image_field']}'; "  # pylint: disable=line-too-long
                        f"// {template_config['description']}\n}}"
                    )
                    display_js = display_js.replace(old_func, new_func)
                js_parts.append(display_js)

        # Add effects JavaScript
        for effect in template_config.get("effects", []):
            if effect_js := self.load_component("js", effect):
                js_parts.append(effect_js)

        # Add WebSocket setup (only for websocket-base templates)
        if family_config["base"] == "websocket-base":
            for ws_component in family_config.get("common_websocket", []):
                if ws_js := self.load_component("websocket", ws_component):
                    js_parts.append(ws_js)

        return js_parts

    @staticmethod
    def _build_external_imports(family_config: dict[str, Any]) -> list[str]:
        """Build external import tags for CSS and JS"""
        external_imports = []
        external_imports.extend(
            f'<link rel="stylesheet" href="{ext_css}">'
            for ext_css in family_config.get("external_css", [])
        )
        external_imports.extend(
            f'<script src="{ext_js}"></script>' for ext_js in family_config.get("external_js", [])
        )
        return external_imports

    @staticmethod
    def _create_template_context(  # pylint: disable=too-many-arguments
        family_config: dict[str, Any],
        template_config: dict[str, Any],
        template_name: str,
        css_parts: list[str],
        js_parts: list[str],
        body_content: str,
        external_imports: list[str],
    ) -> dict[str, Any]:
        """Create the template rendering context"""
        return {
            "template_title": template_config.get("title", template_name),
            "font_link": family_config.get("font_link") or template_config.get("font_link"),
            "css_content": "\n\n".join(css_parts),
            "js_content": "\n\n".join(js_parts) if js_parts else None,
            "body_content": body_content,
            "external_imports": "\n    ".join(external_imports) if external_imports else None,
            "refresh_rate": template_config.get("refresh_rate"),
        }

    def build_template_family(self, family_name: str, family_config: dict[str, Any]) -> None:
        """Build all templates in a family"""
        print(f"Building family: {family_name}")
        base_template = self.jinja_env.get_template(f"{family_config['base']}.jinja2")

        for template_name, template_config in family_config["templates"].items():
            print(f"  Building: {template_name}")

            # Gather all content components
            css_parts = self._gather_css_content(family_config, template_config)
            js_parts = self._gather_js_content(family_config, template_config)

            # Get body layout
            body_content = ""
            if template_config.get("body_layout"):
                body_content = self.load_component("html", template_config["body_layout"])

            # Build external imports
            external_imports = self._build_external_imports(family_config)

            # Create template context
            context = self._create_template_context(
                family_config,
                template_config,
                template_name,
                css_parts,
                js_parts,
                body_content,
                external_imports,
            )

            # Render and write template
            output = base_template.render(context)
            output_file = self.output_dir / f"{template_name}.htm"
            output_file.write_text(output)
            print(f"    Generated: {output_file}")

    @staticmethod
    def download_vendor_file(
        filename: str, url: str, vendor_cache_dir: Path, vendor_out_dir: Path
    ) -> bool:
        """Download a vendor file if it doesn't exist in cache"""
        cache_file = vendor_cache_dir / filename
        output_file = vendor_out_dir / filename

        # Check if file exists in cache
        if not cache_file.exists():
            print(f"    Downloading {filename} from {url}")
            try:
                urllib.request.urlretrieve(url, cache_file)
                print(f"    Downloaded: {cache_file}")
            except (OSError, ValueError) as err:
                print(f"    Error downloading {filename}: {err}")
                return False
        else:
            print(f"    Using cached: {cache_file}")

        # Copy from cache to output (handle both text and binary files)
        try:
            # Try binary copy first (works for all file types)
            output_file.write_bytes(cache_file.read_bytes())
        except OSError as err:
            print(f"    Error copying {filename}: {err}")
            return False
        print(f"    Copied vendor file: {output_file}")
        return True

    def setup_vendor_files(self) -> None:
        """Download and setup vendor JavaScript files"""
        vendor_config_file = self.src_dir / "vendor.yaml"
        vendor_cache_dir = self.src_dir / "vendor"
        vendor_out_dir = self.output_dir / "vendor"

        # Create directories
        vendor_cache_dir.mkdir(exist_ok=True)
        vendor_out_dir.mkdir(exist_ok=True)

        # Load vendor configuration
        if not vendor_config_file.exists():
            print(f"No vendor config found at {vendor_config_file}")
            return

        try:
            config = yaml.safe_load(vendor_config_file.read_text())
            dependencies = config.get("vendor_dependencies", {})

            for filename, info in dependencies.items():
                url = info["url"]
                version = info.get("version", "unknown")
                description = info.get("description", filename)

                print(f"Processing {description} v{version}")
                self.download_vendor_file(filename, url, vendor_cache_dir, vendor_out_dir)

        except (OSError, yaml.YAMLError) as err:
            print(f"Error processing vendor config: {err}")

    def copy_vendor_files(self) -> None:
        """Setup vendor files using configuration-based downloads"""
        self.setup_vendor_files()

    def cleanup_orphaned_templates(self) -> None:
        """Remove generated template files that are no longer in any configuration"""
        print("Checking for orphaned template files...")

        # Collect all template names from all configs
        active_templates = set()
        for config_file in (self.src_dir / "configs").glob("*.yaml"):
            config = yaml.safe_load(config_file.read_text())
            for family_config in config["template_families"].values():
                for template_name in family_config["templates"].keys():
                    active_templates.add(f"{template_name}.htm")

        # Check existing template files
        template_files = list(self.output_dir.glob("*.htm"))
        for template_file in template_files:
            if template_file.name not in active_templates:
                print(f"  Removing orphaned template: {template_file.name}")
                template_file.unlink()

    def build_all(self) -> None:
        """Build all template families"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Copy vendor files first
        self.copy_vendor_files()

        # Clean up orphaned templates before building
        self.cleanup_orphaned_templates()

        for config_file in (self.src_dir / "configs").glob("*.yaml"):
            print(f"Processing config: {config_file.name}")
            config = yaml.safe_load(config_file.read_text())

            for family_name, family_config in config["template_families"].items():
                self.build_template_family(family_name, family_config)

    def build_family(self, family_name: str) -> None:
        """Build a specific template family"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        for config_file in (self.src_dir / "configs").glob("*.yaml"):
            config = yaml.safe_load(config_file.read_text())

            if family_name in config["template_families"]:
                family_config = config["template_families"][family_name]
                self.build_template_family(family_name, family_config)
                return

        print(f"Family '{family_name}' not found in any config file")


if __name__ == "__main__":
    import sys

    builder = TemplateBuilder()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--family":
            if len(sys.argv) > 2:
                builder.build_family(sys.argv[2])
            else:
                print("Usage: build_templates.py --family <family_name>")
        else:
            print("Usage: build_templates.py [--family <family_name>]")
    else:
        builder.build_all()
