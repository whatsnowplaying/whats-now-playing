#!/usr/bin/env python3
"""
MkDocs macros for dynamic documentation generation.

This file provides macros that can be used in MkDocs pages to dynamically
generate content from the template build system configuration files.
"""

import pathlib
import yaml


def define_env(env):
    """
    Define macros for MkDocs.

    This function is automatically called by mkdocs-macros-plugin.
    """

    @env.macro
    def template_reference() -> str:
        """
        Generate template reference documentation from YAML configuration files.

        Returns:
            Formatted markdown string with all templates organized by category
        """
        config_dir = pathlib.Path("template-src/configs")

        # Check if we're running from the docs directory
        if not config_dir.exists():
            # Try relative to project root when building docs
            config_dir = pathlib.Path("../template-src/configs")

        if not config_dir.exists():
            return "*Template configuration files not found. Run from project root.*"

        configs = {}

        # Load all template configuration files
        for yaml_file in config_dir.glob("*.yaml"):
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "template_families" in data:
                    configs[yaml_file.stem] = data["template_families"]

        if not configs:
            return "*No template configurations found.*"

        # Generate markdown content
        markdown_parts = []

        for config_file, families in configs.items():
            # Convert filename to readable title
            title = config_file.replace("-", " ").title()
            markdown_parts.append(f"## {title}")
            markdown_parts.append("")

            for family_name, family_data in families.items():
                family_desc = family_data.get("description", "No description available")
                family_title = family_name.replace("_", " ").title()

                markdown_parts.append(f"### {family_title}")
                markdown_parts.append("")
                markdown_parts.append(f"*{family_desc}*")
                markdown_parts.append("")

                templates = family_data.get("templates", {})
                if templates:
                    markdown_parts.append("| Template | Description |")
                    markdown_parts.append("|----------|-------------|")

                    for template_name, template_data in templates.items():
                        desc = template_data.get("description", "No description available")
                        markdown_parts.append(f"| `{template_name}.htm` | {desc} |")

                    markdown_parts.append("")
                else:
                    markdown_parts.append("*No templates defined in this family.*")
                    markdown_parts.append("")

        return "\n".join(markdown_parts)
