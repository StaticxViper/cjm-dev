# Portfolio

Personal site for Chris Moulton. It is a static page: one HTML file, one stylesheet, and a resume PDF. There is no backend.

GitHub Pages publishes the built site at [https://staticxviper.github.io/cjm-dev/](https://staticxviper.github.io/cjm-dev/).

## Update the content

All visible copy lives in [`content.json`](content.json): name, bio, experience, projects, skills, education, certifications, honors, and contact links.

1. Edit `portfolio/content.json`.
2. From the repository root, rebuild:

   ```bash
   python portfolio/build.py
   ```

3. Open `portfolio/dist/index.html` in a browser and check the page, including a narrow window.
4. Commit `content.json` and the regenerated resume PDF.

Dates and job titles follow the LinkedIn profile export when it is more specific than the older resume (for example, the ASRC Federal promotion in March 2026). Accomplishments, projects, skills, coursework, and certifications come from the resume and the profile together.

The LinkedIn export used as a source is stored at [`sources/Profile.pdf`](sources/Profile.pdf). The site does not read that PDF. After a new export, replace the file and update `content.json` to match.

## Update the resume

By default the build writes `portfolio/public/Christopher-Moulton-Resume.pdf` from `content.json`, then copies it into the site. The Download resume button links to that file.

To publish a resume you designed yourself:

1. Save it as `portfolio/public/Christopher-Moulton-Resume.pdf`.
2. Set `"generateResume": false` in `content.json` so the next build keeps your file.
3. Run `python portfolio/build.py`.

Set `generateResume` back to `true` if you want the PDF generated from `content.json` again.

## Deploy

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) builds the site and deploys it to GitHub Pages when `main` is pushed. You can also run it by hand from the Actions tab (workflow_dispatch).

The repository Pages source has to be **GitHub Actions** (Settings → Pages → Build and deployment → Source). The first successful run of this workflow publishes [https://staticxviper.github.io/cjm-dev/](https://staticxviper.github.io/cjm-dev/).
