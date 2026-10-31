# GitHub setup and releases

This repository is prepared for a public MIT-licensed project. Publishing is a separate maintainer action. Local preparation does not create a GitHub repository, upload code, publish packages, or change a running installation.

## First publication

1. Review the staged files and the release-boundary check. Instance configuration, `.env` files, provider credentials, private operations notes, databases, generated builds and `.validation/` must remain excluded.
2. Set the Git name/email you want in the public commit history; use your GitHub no-reply address if preferred. Make the initial commit on `main`.
3. Create an empty GitHub repository under your account or organization. Keep its name consistent with the image/documentation examples, or update them.
4. Add its real remote URL and push `main`. Replace the placeholders below; no remote is preconfigured.

```sh
git diff --cached --stat
python scripts/check_public_files.py
git commit -m "Prepare QuillSail for open source"
git remote add origin https://github.com/YOUR_ACCOUNT/copydesk.git
git push -u origin main
```

In repository settings, enable Issues, private vulnerability reporting, Dependabot alerts/updates and secret push protection where available. Set branch rules for `main` that require passing CI and review appropriate to the maintainer team. Add real maintainer/support contacts to SECURITY.md and CODE_OF_CONDUCT.md when those are established. Do not put a production SSH key, SMTP password, instance secret key or database URL into GitHub Actions; this project's CI needs none of them.

GitHub settings depend on account/repository capabilities and must be configured by the owner. See [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository).

## CI

`.github/workflows/tests.yml` runs on pull requests, pushes to `main`, and manual dispatch. Development-branch pushes are checked through their pull requests, avoiding duplicate runs. It checks Python 3.11–3.14, PostgreSQL/MariaDB, lint, public-file boundaries, wheel/sdist metadata, a clean wheel installation, and a Docker/Compose smoke deployment. Each database job starts only its own database service. Action versions are pinned to commit hashes; Dependabot proposes updates for actions, Python dependencies and the base image.

Python jobs cache pip downloads using their dependency manifests. Desktop builds use a separate cache for their larger native dependencies, including compiled cryptography wheels; macOS keeps `OPENSSL_STATIC=1` and checks OpenSSL linkage before packaging. Obsolete pull-request desktop builds are canceled, while release publishing and signed-feed updates are never canceled by this policy. All four native lifecycle and updater checks still run for desktop changes and every published desktop release.

Pull-request CI has read-only repository permission and no production credentials. The container test uses its own disposable Compose project/volume and synthetic first-run setup. The default source build and all release archives exclude local secrets and instance data.

## Release a version

1. Update `copydesk.__version__`, the changelog and verification notes. Run the relevant tests and package/container checks. Keep the version immutable after publication.
2. Push the reviewed commit and a matching tag such as `v1.3.0`.
3. Publish a GitHub release for that tag. Mark beta releases as prereleases. Merely pushing `main` or a tag does not run the publishing workflow.

The Release workflow requires the tag to equal `v` plus the package version. It validates the source, runs tests and a clean package install, then attaches the wheel and source archive. Its image job builds and smoke-tests a container before publishing to `ghcr.io/<owner>/<repository>:<version>` using GitHub's built-in token. Stable releases can also update `latest`; prereleases do not. The initial registry image targets Linux amd64.

After the first image publication, check that the package is linked to the repository and has the intended public visibility before advertising anonymous pulls. The workflow does not publish to PyPI, SSH into servers or deploy automatically. Package publication on another registry requires ownership and an explicit maintainer configuration.

See GitHub's [container publishing guide](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images). Users deploy the image or source using [installation](installation.md), then manage backups/upgrades with [maintenance](maintenance.md).

## Desktop downloads

Run **Desktop bundles** on `main` and enable its **publish** checkbox to publish the desktop beta. Leave that option off for build-only verification. The workflow uses separate Apple Silicon, Intel Mac, Windows x64 and Linux x64 runners, verifies both browser setup/restart and GUI startup/stop/restart, and collects all four archives before publishing. It includes SHA-256 checksums and build reports tied to the exact source commit.

The publisher creates a draft first and publishes it only after every upload is verified. It can resume the same draft after an upload failure and refuses to replace an already published version. Bump `copydesk.__version__` before changing published downloads. The built-in workflow token does not trigger the separate Release workflow, so publishing desktop downloads this way does not publish a container. See GitHub's [workflow trigger behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

Manual Intel Mac release jobs apply [GitHub's documented workaround for ticket-download failures](https://github.com/actions/runner-images/issues/14924): block UDP port 443 in the disposable runner so Apple's stapler uses HTTPS over TCP. This avoids the runner's broken HTTP/3 path. Other platforms and pull-request jobs keep their existing network configuration. Developer ID signing, certificate verification, accepted notarization, ticket stapling and validation remain required; a failed check blocks publication.

## Local release checks

```sh
pip install -e '.[dev,integration]'
pytest
ruff check src tests scripts deploy
python scripts/check_public_files.py
python -m build
python -m twine check --strict dist/*
python scripts/check_public_files.py --archive dist/*.whl
python scripts/check_public_files.py --archive dist/*.tar.gz
python scripts/package_smoke.py dist/*.whl
docker build -t copydesk:ci .
bash scripts/container_smoke.sh
```

Use a clean output directory when building: release workflows start from fresh checkouts, whereas a developer's local `dist/` may contain older versions. The boundary checker catches excluded file types and recognizable key/token formats; also review staged content for organization-specific/private information.
