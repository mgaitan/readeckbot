.PHONY: release
release: ## Create a GitHub release for the current version
	@version=$$(grep -Po '(?<=__version__ = \")([^\"]+)' readeckbot/__init__.py); \
	echo "🚀 Creating release for version $$version".; \
	gh release create "$$version" --generate-notes
