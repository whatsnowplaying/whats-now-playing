#!/usr/bin/env python3
"""MkDocs macros for dynamic documentation generation."""

import wnp_templates


def define_env(env):
    """Define macros for MkDocs. Called automatically by mkdocs-macros-plugin."""

    @env.macro
    def template_reference() -> str:
        """Generate template reference documentation from wnp_templates."""
        try:
            return _generate_template_reference()
        except Exception as error:  # pylint: disable=broad-exception-caught
            return f"*Error generating template reference: {error}*"

    def _generate_template_reference() -> str:
        markdown_parts = []
        for family_name, effects in wnp_templates.TEMPLATE_FAMILIES.items():
            desc = wnp_templates.TEMPLATE_FAMILY_DESCRIPTIONS.get(family_name, "")
            markdown_parts.append(f"### {family_name}")
            markdown_parts.append("")
            if desc:
                markdown_parts.append(f"*{desc}*")
                markdown_parts.append("")
            markdown_parts.append("| Effect | Template |")
            markdown_parts.append("|--------|----------|")
            for effect, stem in effects.items():
                markdown_parts.append(f"| {effect} | `{stem}.htm` |")
            markdown_parts.append("")
        return "\n".join(markdown_parts)
