# QuillSail branding

The brand name is **QuillSail**, with capital Q and S. The primary logo color is purple, `#6E4CC2`.

- `QuillSail.svg` is the original vector master. Use SVG for websites and documentation.
- `QuillSail.png` is the supplied transparent raster export. Use PNG for email clients.
- Packaged copies live in `src/copydesk/static/brand/`. The web SVG omits the external document type declaration; its shapes and purple fill match the master.
- The desktop launcher renders the SVG directly. Keep it as a vector rather than scaling a small bitmap; desktop app icons are rasterized from this master at full resolution when building.

Use the purple mark on light surfaces. The application renders it white on dark web surfaces for contrast. Keep the artwork's aspect ratio and provide the QuillSail name alongside it when space allows.

QuillSail is the software identity. A hosted blog or newsletter keeps its own publication name, logo, and accent color.

## Interface style

QuillSail's own screens look like print: ink on paper, hairline rules, and the logo purple as the only accent. This covers the desktop launcher and the first-time setup page. New publications also start in this style, as the QuillSail starting style on the website, in newsletter emails and in the dashboard's own design. Each publication can then change its publication and dashboard designs separately, or have the dashboard match the publication.

- **Color.** Use only black, white and the logo purple, `#6E4CC2`. In the QuillSail wordmark, "Quill" is always the logo purple and "Sail" uses the text color. Light is the default. People can choose Dark, or Automatic to follow the system. Dark mode softens white to reduce glare: 86% for text and the logo, 40% for borders and rules, and 14% for hover fills. Disabled controls use 40% ink in light mode and 30% in dark mode.
- **Purple.** Reserve it for the logo, "Quill" in the wordmark, the primary action, keyboard focus, progress, selected text and form errors. Put white text on purple. Avoid purple text on black except at display sizes like the wordmark: it meets WCAG AA only as large text.
- **Errors.** Mark a field with a 2px purple rule on its left and state the problem in plain text. Do not introduce red or other colors.
- **Headings.** Amiri Bold (700). In the launcher, use 42px for the QuillSail nameplate and 26px for the status line. On the web, the nameplate and page heading scale with the screen. The font is bundled as `src/copydesk/static/fonts/Amiri-Bold.ttf` under the SIL Open Font License; keep `OFL.txt` beside the font file. Amiri's line box is tall to leave room for Arabic marks: on the web, keep heading line heights at 1.1 or less, and in the launcher, `trim_line_box()` removes the space Latin text leaves empty.
- **Body text.** Iowan Old Style or Charter, then Sitka Text, Palatino Linotype and Georgia. This is the web app's serif stack. Use 14px in the launcher and the browser default size on the web, with italic for notes.
- **Labels and buttons.** Avenir Next, then Helvetica Neue, Segoe UI, Helvetica and Arial. Section labels are small semibold capitals with wide letter spacing (11px with 1.4px spacing in the launcher). Field labels are semibold, in sentence case. Buttons are medium or semibold, in sentence case.
- **Shape.** Square corners and no shadows. A 2px rule sits under the nameplate, and 1px rules separate sections. Controls have 1px borders; keyboard focus draws a 2px purple border.

In the launcher, the styles live in `STYLE` in `src/copydesk/desktop_ui.py` and apply to the whole application, so dialogs match the window. Set fonts in that stylesheet, not with Qt's per-class application fonts, which macOS resets after startup.

On the web, setup styles live in `src/copydesk/static/css/setup.css`, scoped to `.setup-page`. The QuillSail style for publications and dashboards lives in `src/copydesk/static/css/publication.css`, scoped to `.design-quillsail`, with its colors in the `quillsail` preset in `src/copydesk/appearance.py`. Links there stay ink with an underline, and secondary text stays full ink. Setup follows the launcher's appearance: the launcher passes Light, Dark or Automatic to each publication it runs, and other installations use Light. The page renders that theme on the server and ignores a theme saved in the browser.
