# Section Reference Guide

This guide is the dynamic source of truth for all available UI sections.
Generated from `astro-basic/src/components/sections/` by `templates/generate_sections_doc.py` — do not edit by hand.


## `<Article />`
Article Component - A content card with a heading and one or more body paragraphs. Use this for article intros, about-us prose, or any long-form text section.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#about") |
| `badge` | no | `string` | Optional small badge label shown above the heading (e.g. "Featured", "News") |
| `heading` | no | `string` | Section heading |
| `subheading` | no | `string` | Optional subtitle displayed directly below the heading |
| `paragraphs` | yes | `string[]` | One or more paragraphs of body text |
| `fontFamily` | no | `'sans' \| 'serif' \| 'mono'` | Primary font family for paragraphs: 'sans' (default), 'serif', or 'mono' |
| `image` | no | `{ src: string; alt: string; }` | Optional full-width image |
| `images` | no | `Array<{ src: string; alt: string; }>` | Optional array of images for split layout (alternative to single image) |
| `imagePosition` | no | `'top' \| 'bottom' \| 'left' \| 'right'` | Where to render the image relative to the text: 'top' (above heading), 'bottom' (default, below paragraphs), 'left' or 'right' (side-by-side split layout) |
| `imageCircular` | no | `boolean` | If true, renders image as circular and overlapping the top of the card |
| `imageAlign` | no | `'left' \| 'center' \| 'right'` | Horizontal alignment for circular images: 'left' (default), 'center', or 'right' |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class, e.g., 'bg-gray-100') |
| `textColor` | no | `string` | Text color for heading and paragraphs (Tailwind class, e.g., 'text-white'). Overrides the default dark-on-light palette — use when backgroundColor is dark. |
| `headingColor` | no | `string` | Override color for the heading only (Tailwind class, e.g., 'text-pink-500'). Takes precedence over textColor for the heading element. |
| `badgeColor` | no | `string` | Override color for the badge label (Tailwind class, e.g., 'text-red-700'). Defaults to 'text-indigo-500'. |
| `card` | no | `boolean` | If true, renders paragraphs inside a raised card |
| `cardBackgroundColor` | no | `string` | Background color for the raised card (Tailwind class, e.g., 'bg-gray-100'). Defaults to 'bg-white' when card=true. |
| `maxWidth` | no | `string` | Max width constraint (Tailwind class, e.g., 'max-w-3xl') |
| `layout` | no | `'default' \| 'centered' \| 'wide' \| 'split'` | Section layout variant: 'default' (card + maxWidth), 'centered' (centered text, no card), 'wide' (full-width, no maxWidth constraint), 'split' (two-column: text on left, map/image on right) |
| `action` | no | `{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }` | Optional CTA button rendered below the text |
| `actions` | no | `Array<{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }>` | Multiple CTA buttons rendered below the text |
| `actionAlign` | no | `'left' \| 'center' \| 'right'` | Alignment for action buttons: 'left' (default), 'center', or 'right' |
| `sidebar` | no | `{ title?: string; links?: Array<{ label: string; href: string; }>; sections?: Array<{ title: string; content?: string; links?: Array<{ label: string; href: string; }> }>; image?: { src: string; alt: string; }; content...` | Optional sidebar with a title and list of links; renders a two-column layout (position controlled by sidebarPosition) |
| `sidebarPosition` | no | `'left' \| 'right'` | Which side to render the sidebar: 'left' (default) or 'right' |
| `sidebarBackgroundColor` | no | `string` | Background color for the sidebar (Tailwind class, e.g., 'bg-yellow-800'). Overrides sidebar.backgroundColor when present. |
| `backgroundImage` | no | `string` | Background image URL — creates a full-cover background with a subtle overlay |
| `map` | no | `{ src: string; width?: string; height?: string; heading?: string; }` | Optional embedded iframe (e.g., Google Maps embed or YouTube video); rendered below paragraphs, or in the right column when layout='split' |
| `videoEmbed` | no | `string` | YouTube or other iframe embed URL; rendered as a responsive 16:9 iframe below the paragraphs |
| `bulletPoints` | no | `string[]` | Optional bulleted list of items rendered after paragraphs |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment: 'left' (default), 'center', or 'right' — mirrors Hero.align |

---

## `<Banner />`
Banner Component - A horizontal bar for notifications, secondary CTAs, or brand highlighting.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#promo") |
| `text` | yes | `string` | The text content of the banner |
| `backgroundColor` | no | `string` | Optional background color (Tailwind class) |
| `textColor` | no | `string` | Optional text color (Tailwind class) |
| `action` | no | `{ label: string; href: string; }` | Optional link/CTA |
| `sticky` | no | `boolean` | If true, the banner is fixed to the top of the viewport |
| `fixedPosition` | no | `'top' \| 'bottom'` | Position for fixed banners: 'top' (default) or 'bottom' |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment: 'left', 'center' (default), or 'right' |

---

## `<Calendar />`
Calendar Component - Displays a grid of events or a schedule.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#events") |
| `backgroundColor` | no | `string` | Background color for the section (Tailwind class, e.g. 'bg-black') |
| `textColor` | no | `string` | Base text color applied to the whole section (Tailwind class, e.g. 'text-white'). Use when backgroundColor is dark. |
| `heading` | no | `string` | Section heading |
| `subheading` | no | `string` | Supporting description |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'center' (default), 'left', or 'right' |
| `events` | yes | `Array<{ date: string; title: string; description?: string; time?: string; }>` | Array of events |

---

## `<ContactForm />`
ContactForm Component - Property-Driven Architecture Inspired by Fulldev UI for maximum AI-compatibility.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#reservation") |
| `backgroundColor` | no | `string` | Tailwind background-color utility applied to the section (e.g. "bg-pink-50", "bg-white") |
| `textColor` | no | `string` | Tailwind text-color utility applied as the base text color (e.g. "text-white"). Use when backgroundColor is dark. |
| `backgroundImage` | no | `string` | Background image URL — creates a full-cover background with a subtle overlay |
| `heading` | no | `string` | — |
| `subheading` | no | `string` | — |
| `email` | no | `string` | — |
| `successMessage` | no | `string` | — |
| `card` | no | `boolean` | If true (default), wraps the form in a raised card container |
| `cardBackgroundColor` | no | `string` | Background color for the card container (Tailwind class, e.g., 'bg-gray-50', 'bg-white'). Only applied when card=true. |
| `buttonLabel` | no | `string` | Label text for the submit button (e.g. "Send", "Submit", "Get in touch") |
| `buttonVariant` | no | `'primary' \| 'secondary' \| 'success' \| 'danger'` | — |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'left' (default), 'center', or 'right' |
| `layout` | no | `'centered' \| 'split'` | — |
| `maxWidth` | no | `string` | Max width constraint for the form container (Tailwind class, e.g., 'max-w-sm', 'max-w-md') |
| `fullHeight` | no | `boolean` | If true, the form section takes up at least the full height of the screen (useful with backgroundImage) |
| `sidebar` | no | `{ title?: string; content?: string; address?: string[]; phone?: string; email?: string; }` | — |
| `fields` | no | `Array<{ label: string; type: 'text' \| 'email' \| 'textarea' \| 'password' \| 'select' \| 'date' \| 'time' \| 'number'; required?: boolean; placeholder?: string; options?: string[]; }>` | Options for select field type |
| `image` | no | `{ src: string; alt?: string; }` | Optional image shown in the right column when layout='split' |

---

## `<Features />`
Features Component - Property-Driven Architecture

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#features") |
| `heading` | no | `string` | — |
| `subheading` | no | `string` | — |
| `columns` | no | `2 \| 3 \| 4` | — |
| `layout` | no | `'grid' \| 'list'` | Layout variant: 'grid' for multi-column card grid (default), 'list' for full-width stacked rows |
| `backgroundColor` | no | `string` | — |
| `backgroundImage` | no | `string` | Background image URL — creates a full-cover background behind the features grid |
| `textColor` | no | `string` | Base text color applied to heading, subheading, and feature titles/descriptions (Tailwind class, e.g. 'text-white'). Use when backgroundColor is dark. |
| `headingColor` | no | `string` | Override color for the section heading only (Tailwind class, e.g. 'text-yellow-600'). Takes precedence over textColor for the h2 element. |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for the section header and feature card content: 'center' (default), 'left', or 'right' |
| `action` | no | `{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }` | Optional section-level CTA button rendered below the features grid |
| `features` | yes | `Array<{ title: string; description: string; icon?: string; image?: string; backgroundColor?: string; headingColor?: string; action?: { label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }; }>` | Optional CTA button shown below the description |

---

## `<Footer />`
Footer Component - A site footer with links and information. The template already renders an automatic site-wide footer from settings.yaml on every page; when you add this <Footer> section to a page, also set `hideFooter: true` in that page's frontmatter so your footer replaces the automatic one.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional id for anchor links |
| `columns` | yes | `Array<{ title: string; links?: Array<{ label: string; href: string; }>; text?: string[]; }>` | Plain text lines rendered as paragraphs (e.g. address, phone, email) |
| `logo` | no | `{ src: string; alt?: string; }` | Optional logo image displayed next to siteName |
| `siteName` | no | `string` | Site name or logo text |
| `description` | no | `string` | Short description |
| `copyright` | no | `string` | Copyright text |
| `backgroundColor` | no | `string` | Tailwind background color class |
| `textColor` | no | `string` | Tailwind text color class |
| `fixedPosition` | no | `boolean` | If true, the footer is fixed to the bottom of the viewport |
| `newsletter` | no | `{ heading?: string; placeholder?: string; buttonLabel?: string; }` | Optional newsletter subscribe form rendered as the last column |
| `action` | no | `{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }` | Optional CTA button rendered in the bottom copyright bar |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for footer content: 'left' (default), 'center', or 'right' |
| `linkColor` | no | `string` | Text color for footer links (Tailwind class, e.g., 'text-pink-500') |

---

## `<Gallery />`
Gallery Component - Property-Driven Architecture

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#gallery") |
| `backgroundColor` | no | `string` | Background color for the section (Tailwind class, e.g. 'bg-gray-100') |
| `textColor` | no | `string` | Text color for heading and subheading (Tailwind class, e.g. 'text-white'). Use when backgroundColor is dark. |
| `headingColor` | no | `string` | Specific heading color override (Tailwind class, e.g. 'text-pink-500'). Takes precedence over textColor for the heading. |
| `heading` | no | `string` | — |
| `subheading` | no | `string` | — |
| `columns` | no | `2 \| 3 \| 4` | — |
| `layout` | no | `'stacked' \| 'split'` | — |
| `sidebar` | no | `{ title?: string; content?: string; image?: { src: string; alt: string; }; links?: Array<{ label: string; href: string; }>; action?: { label: string; href: string; }; }` | Optional sidebar content |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'center' (default), 'left', or 'right' — mirrors Hero.align |
| `backgroundImage` | no | `string` | Background image URL — creates a full-cover background with a subtle overlay |
| `action` | no | `{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }` | Optional CTA button rendered below the image grid |
| `maxWidth` | no | `string` | Max width constraint (Tailwind class, e.g., 'max-w-3xl') |
| `images` | yes | `Array<{ src: string; alt: string; caption?: string; title?: string; description?: string; artist?: string; overlayText?: string; overlayPosition?: 'center' \| 'top' \| 'bottom'; action?: { label: string; href: string; v...` | — |

---

## `<Header />`
Header Component - A horizontal header with logo on the left and contact info on the right.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `logo` | no | `{ src: string; alt?: string; size?: string; }` | Optional logo image shown on the left side |
| `siteName` | no | `string` | Brand name rendered as bold text on the left when no logo is provided |
| `heading` | no | `string` | Main heading text displayed prominently (e.g., "Welcome to Tech Startup") |
| `image` | no | `{ src: string; alt?: string; }` | Optional image displayed alongside the site name (e.g. school emblem, badge) |
| `paragraphs` | no | `string[]` | Body paragraphs displayed below the heading |
| `contactInfo` | no | `Array<{ label: string; value: string; }>` | Contact information displayed on the right side |
| `cta` | no | `{ label: string; href: string; }` | Optional call-to-action button shown on the right side |
| `links` | no | `Array<{ label: string; href: string; }>` | Navigation links rendered as a horizontal nav bar |
| `linkColor` | no | `string` | Text color for navigation links (Tailwind class, e.g., 'text-yellow-500') |
| `backgroundColor` | no | `string` | Background color for the header (Tailwind class) |
| `backgroundGradient` | no | `string` | Background gradient for the header (e.g., 'from-purple-500 to-pink-500' for use with bg-gradient-to-r) |
| `textColor` | no | `string` | Text color for the header (Tailwind class) |
| `showSearch` | no | `boolean` | Whether to show a search input in the header |
| `searchPlaceholder` | no | `string` | Placeholder text for the search input |
| `searchButtonLabel` | no | `string` | Label for the search submit button (shown when showSearch is true) |
| `backgroundImage` | no | `string` | Background image URL — creates a full-cover background with optional overlay |
| `minHeight` | no | `string` | Min height for the header when using backgroundImage (e.g., 'h-64') |
| `subheading` | no | `string` | Optional subtitle displayed below the site name or heading |
| `align` | no | `'left' \| 'center' \| 'right'` | Text/content alignment within the header: 'left' (default), 'center', or 'right' |
| `fixedTop` | no | `boolean` | If true, header is fixed to the top of the viewport |
| `loginForm` | no | `{ usernameLabel?: string; usernamePlaceholder?: string; passwordLabel?: string; passwordPlaceholder?: string; buttonLabel?: string; buttonColor?: string; }` | Optional login form displayed on the right side |
| `showHamburger` | no | `boolean` | If true, shows a hamburger menu button on the right side |
| `imageCircular` | no | `boolean` | If true, renders the image as circular (rounded-full) |
| `logoAlign` | no | `'left' \| 'center' \| 'right'` | Logo horizontal alignment: 'left' (default), 'center', or 'right' |
| `imageAlign` | no | `'left' \| 'center' \| 'right'` | Horizontal alignment for images: 'left' (default), 'center', or 'right' |
| `selectOptions` | no | `string[]` | Optional select dropdown options displayed in header |
| `selectLabel` | no | `string` | Label for the select dropdown |

---

## `<Hero />`
Hero Component - The primary visual hook at the top of a page. Use this for high-impact messaging and primary calls to action.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional ID for anchor linking |
| `heading` | no | `string` | The main large title (e.g., "Transform Your Business"). Omit for image-only hero sections. |
| `subheading` | no | `string` | Supporting text below the heading |
| `mono` | no | `boolean` | If true, uses monospace font for the subheading |
| `fontFamily` | no | `'sans' \| 'serif' \| 'mono'` | Primary font family for heading |
| `fontWeight` | no | `'bold' \| 'extrabold' \| 'black'` | Font weight for heading |
| `badge` | no | `string` | A small label shown above the heading |
| `logo` | no | `{ src: string; alt?: string; size?: string; circular?: boolean; }` | Optional logo shown above everything |
| `actions` | no | `Array<{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }>` | Array of CTA buttons |
| `cta` | no | `{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }` | Optional single CTA button (alternative to actions) |
| `action` | no | `{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }` | Optional CTA button rendered below the text (alternative to cta) |
| `align` | no | `'center' \| 'left' \| 'right'` | Text alignment: 'center' (default), 'left' or 'right' |
| `layout` | no | `'split' \| 'stacked'` | Layout style: 'split' (side-by-side) or 'stacked' (vertical) |
| `fullHeight` | no | `boolean` | If true, the section will take up at least the full height of the screen |
| `minHeight` | no | `string` | Tailwind min-height class to set a custom minimum height (e.g., 'min-h-[600px]', 'min-h-96'). Ignored when fullHeight is true. |
| `showSearch` | no | `boolean` | If true, show a large search bar |
| `searchPlaceholder` | no | `string` | Search bar placeholder text |
| `searchFields` | no | `Array<{ placeholder: string; type?: string }>` | Custom search fields for multi-input search forms |
| `searchButtonLabel` | no | `string` | Search form button label |
| `image` | no | `{ src: string; alt: string; }` | Main visual image |
| `images` | no | `Array<{ src: string; alt: string; }>` | Array of images for gallery/carousel layout (alternative to single image) |
| `backgroundImage` | no | `string` | Background image URL (creates a full-cover background with overlay) |
| `backgroundVideo` | no | `string` | Background video URL (creates a full-cover background video with overlay) |
| `backgroundColor` | no | `string` | Background color (Tailwind class, e.g., 'bg-indigo-600') |
| `headingColor` | no | `string` | Optional heading color (Tailwind class) |
| `subheadingColor` | no | `string` | Optional subheading color (Tailwind class) |
| `textColor` | no | `string` | Base text color applied to the whole section (Tailwind class, e.g., 'text-white'). Use when backgroundColor is dark and you want all text to inherit a light color. |
| `backgroundGradient` | no | `string` | Background gradient for the hero (e.g., 'from-green-400 via-green-500 to-purple-500' for use with bg-gradient-to-r) |
| `videoEmbed` | no | `string` | YouTube or other iframe embed URL; rendered as a responsive 16:9 iframe in place of the image |
| `videoSrc` | no | `string` | Direct video file URL (mp4/webm); rendered as a native <video> element with controls in place of the image |
| `videoAutoplay` | no | `boolean` | If true, the videoSrc plays automatically (muted, looping, no controls) — use for ambient/background-style split-panel videos |
| `audioSrc` | no | `string` | Direct audio file URL (mp3/wav/ogg); rendered as a native <audio> element with controls |
| `imagePosition` | no | `'top' \| 'bottom' \| 'left' \| 'right'` | Where to render the image relative to the text in stacked layout: 'top' (above heading) or 'bottom' (default, below content). 'left'/'right' act as aliases for layout='split'. |
| `showSidebar` | no | `boolean` | If true, renders a narrow sidebar panel on the left side of the hero |
| `sidebarBackgroundColor` | no | `string` | Background color class for the sidebar panel (e.g., 'bg-white bg-opacity-75') |
| `sidebarContent` | no | `Array<{ heading?: string; items?: string[]; text?: string; }>` | Right-side content panel for split layout: supports headings, lists, and text blocks |
| `newsletter` | no | `{ heading?: string; placeholder?: string; buttonLabel?: string; }` | Optional newsletter signup card rendered on the right side of a split-layout hero (e.g. heading, email input, subscribe button) |
| `sidebar` | no | `{ title?: string; content?: string; linksTitle?: string; links?: Array<{ label: string; href: string; }>; image?: { src: string; alt: string; }; }` | Left-side sidebar for split layout: supports headings, paragraph content, and links |
| `sidebarPosition` | no | `'left' \| 'right'` | Which side to render the sidebar: 'left' (default) or 'right' |
| `sidebarContentBackgroundColor` | no | `string` | Background color for the right-side content panel (Tailwind class) |
| `paragraphs` | no | `string[]` | Additional body paragraphs rendered below the subheading |
| `bulletPoints` | no | `string[]` | Bulleted list items rendered below paragraphs (or subheading if no paragraphs) |
| `maxWidth` | no | `string` | Tailwind max-width class to constrain the inner content container (e.g., 'max-w-3xl', 'max-w-4xl'). Defaults to 'max-w-6xl'. |
| `imageCircular` | no | `boolean` | If true, renders the hero image as a circle (rounded-full). Useful for profile/avatar-style hero images. |
| `imageAlign` | no | `'left' \| 'center' \| 'right'` | Horizontal alignment for circular images: 'left' (default), 'center', or 'right' |
| `card` | no | `boolean` | If true, wraps the text content in a semi-transparent card panel (e.g., for a hero with a background image) |
| `cardBackgroundColor` | no | `string` | Tailwind background/style classes for the card panel (default: 'bg-white bg-opacity-75') |
| `links` | no | `Array<{ label: string; href: string }>` | Inline navigation links rendered as an overlay nav bar across the top of the hero |
| `siteName` | no | `string` | Brand/site name shown on the left side of the overlay nav bar (used alongside links) |
| `linkColor` | no | `string` | Text color for navigation links in the overlay nav bar (Tailwind class, e.g., 'text-pink-300') |
| `fixedTop` | no | `boolean` | If true, header is fixed to the top of the viewport |
| `showHamburger` | no | `boolean` | If true, shows a hamburger menu button on the right side |
| `loginForm` | no | `{ usernameLabel?: string; usernamePlaceholder?: string; passwordLabel?: string; passwordPlaceholder?: string; buttonLabel?: string; buttonColor?: string; }` | Optional login form displayed on the right side |
| `selectOptions` | no | `string[]` | Optional select dropdown options displayed in hero |
| `selectLabel` | no | `string` | Label for the select dropdown |

---

## `<HeroCarousel />`
HeroCarousel Component - Full-screen background slideshow with content.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `slides` | yes | `Array<{ heading: string; subheading?: string; image: string; action?: { label: string; href: string }; }>` | — |

---

## `<ListingGrid />`
ListingGrid Component - Displays a grid of items with metadata (e.g., properties, products). Ideal for real estate, e-commerce, or directory sites.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional ID for anchor linking |
| `heading` | no | `string` | Section heading |
| `subheading` | no | `string` | Section subheading |
| `variant` | no | `'grid' \| 'carousel'` | Layout variant |
| `layout` | no | `'grid' \| 'list'` | Layout arrangement: 'grid' for card grid (default), 'list' for full-width stacked rows |
| `columns` | no | `2 \| 3 \| 4` | Number of columns for grid (md and up) |
| `sidebar` | no | `{ title?: string; sections?: Array<{ title: string; items: Array<{ label: string; href?: string; }>; }>; categories?: Array<{ label: string; href: string; count?: number; }>; filters?: Array<{ label: string; options: ...` | Generic grouped list sections (e.g., contact info, service lists) |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class, e.g., 'bg-gray-100') |
| `backgroundImage` | no | `string` | Background image URL for the outer section (e.g., 'https://example.com/bg.jpg') |
| `textColor` | no | `string` | Text color for headings and labels (Tailwind class, e.g., 'text-white') |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'center' (default), 'left', or 'right' |
| `showSearch` | no | `boolean` | Whether to show a search bar above the grid |
| `searchPlaceholder` | no | `string` | Placeholder text for the search bar |
| `searchFields` | no | `Array<{ placeholder: string; type?: string; }>` | Input type (default: 'text') |
| `searchButtonLabel` | no | `string` | Label for the search submit button shown alongside searchFields (default: 'Search') |
| `items` | yes | `Array<{ title: string; description?: string; price?: string; image: string; alt?: string; href?: string; tags?: string[]; }>` | Array of tags or badges (e.g., ["3 Bed", "2 Bath"]) |

---

## `<Navbar />`
Navbar Component - A horizontal navigation bar with links.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `siteName` | no | `string` | Brand/site name displayed on the left side of the navbar |
| `logo` | no | `{ src: string; alt?: string; size?: string; }` | Tailwind height class, e.g. 'h-10' or 'h-12' |
| `links` | yes | `Array<{ label: string; href: string; dropdown?: Array<{ label: string; href: string; }>; }>` | Array of navigation links |
| `backgroundColor` | no | `string` | Tailwind background color class |
| `textColor` | no | `string` | Tailwind text color class |
| `linkColor` | no | `string` | Tailwind text color class applied to the nav links (defaults to inheriting textColor) |
| `align` | no | `'left' \| 'center' \| 'right'` | Alignment of links: 'left', 'center', or 'right' |
| `sticky` | no | `boolean` | If true, the navbar will stick to the top on scroll |
| `fixedTop` | no | `boolean` | If true, the navbar will be fixed to the top of the viewport |
| `fixedBottom` | no | `boolean` | If true, the navbar will be fixed to the bottom of the viewport |
| `cta` | no | `{ label: string; href: string; }` | Optional CTA button shown at the far right of the navbar |
| `showSearch` | no | `boolean` | If true, show a search input on the right side of the navbar |
| `searchPlaceholder` | no | `string` | Placeholder text for the search input |
| `searchButtonLabel` | no | `string` | Label for the search submit button (default: "Search") |
| `backgroundImage` | no | `string` | Background image URL — renders as a full-cover background behind the navbar |
| `showHamburger` | no | `boolean` | If true, shows a hamburger menu button on the right side |

---

## `<NewsGrid />`
NewsGrid Component - Displays multiple columns of news or content articles. Each column has a heading and contains a list of article cards. Optionally renders a sidebar (e.g. category list) to the left of the grid.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#news") |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class, e.g. 'bg-gray-100') |
| `textColor` | no | `string` | Text color for headings and labels (Tailwind class, e.g. 'text-white') |
| `heading` | no | `string` | Overall section heading displayed above the columns |
| `subheading` | no | `string` | Supporting description shown below the section heading |
| `columns` | no | `2 \| 3 \| 4` | Number of columns in the news grid area |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'center' (default), 'left', or 'right' |
| `sidebar` | no | `{ heading?: string; items: string[]; }` | List of sidebar item labels |
| `sections` | yes | `Array<{ heading: string; articles: Array<{ title: string; description?: string; image?: { src: string; alt: string }; action?: { label: string; href: string }; }>; }>` | Array of column sections, each with a heading and articles |

---

## `<Newsletter />`
Newsletter Component - A simple lead capture form for mailing lists. Typically used in the footer area or as a call-to-action section. NOTE: this component collects an email address ONLY. If the request asks for any additional named field (e.g. first name, last name, phone), use the ContactForm component with a `fields` array instead — Newsletter cannot render extra fields.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#signup") |
| `heading` | yes | `string` | The main title for the newsletter (e.g., "Join our newsletter") |
| `subheading` | no | `string` | Supporting text (e.g., "Stay updated with our latest collections") |
| `placeholder` | no | `string` | Placeholder text for the email input field |
| `buttonLabel` | no | `string` | Label for the submit button |
| `image` | no | `{ src: string; alt: string; }` | Optional image for split layout |
| `layout` | no | `'stacked' \| 'split'` | Layout style: 'stacked' (default) or 'split' (image on left, form on right) |
| `backgroundColor` | no | `string` | Background color (Tailwind class, e.g., 'bg-indigo-600') |
| `textColor` | no | `string` | Base text color for headings and body text (Tailwind class, e.g., 'text-white'). Use when backgroundColor is dark. |
| `buttonColor` | no | `string` | Button color (Tailwind class, e.g., 'bg-pink-500'). Defaults to inheriting from section styling. |

---

## `<Parallax />`
Parallax Component - A multi-layer parallax scroll effect section. Ideal for creating depth and visual interest with layered content.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional ID for anchor linking |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class) |
| `textColor` | no | `string` | Text color for the section (Tailwind class) |
| `layers` | yes | `Array<{ content: string; depth?: number; heading?: string; color?: string; fontSize?: string; }>` | Font size for the content (Tailwind class, e.g., 'text-xl', 'text-2xl') |
| `minHeight` | no | `string` | Minimum height for the parallax section (Tailwind class, default: 'min-h-96') |

---

## `<Pricing />`
Pricing Component - Property-Driven Architecture

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#pricing") |
| `heading` | no | `string` | — |
| `subheading` | no | `string` | — |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class, e.g., 'bg-gray-100') |
| `textColor` | no | `string` | Text color for heading and subheading (Tailwind class, e.g., 'text-white'). Use when backgroundColor is dark. |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'center' (default), 'left', or 'right' |
| `plans` | yes | `Array<{ name: string; price: string; period?: string; description?: string; features: string[]; ctaLabel: string; ctaHref: string; highlighted?: boolean; }>` | — |

---

## `<Sidebar />`
Sidebar Component - A three-column layout with optional left and right sidebars. Ideal for pages with search/navigation sidebars and main content with supplementary content.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links |
| `logo` | no | `{ src: string; alt?: string; }` | Optional logo displayed centered at the top |
| `heading` | no | `string` | Main section heading |
| `subheading` | no | `string` | Main section subheading |
| `links` | no | `Array<{ label: string; href: string; }>` | Navigation links rendered as a horizontal nav bar (e.g., for service categories) |
| `linkColor` | no | `string` | Text color for navigation links (Tailwind class, e.g., 'text-yellow-500') |
| `paragraphs` | no | `string[]` | Optional paragraphs of body text rendered in the main content area |
| `leftSidebar` | no | `{ title?: string; image?: { src: string; alt: string; }; content?: string; sections?: Array<{ title: string; content: string; }>; links?: Array<{ label: string; href: string; }>; showSearch?: boolean; searchPlaceholde...` | Optional CTA button rendered below the links |
| `rightSidebar` | no | `{ title?: string; images?: Array<{ src: string; alt: string; caption?: string; }>; sections?: Array<{ title: string; content: string; }>; links?: Array<{ label: string; href: string; }>; showSearch?: boolean; searchPl...` | Optional CTA button rendered at the bottom of the right sidebar |
| `articles` | no | `Array<{ title?: string; id?: string; description?: string; bulletPoints?: string[]; image?: { src: string; alt: string; }; backgroundColor?: string; textColor?: string; action?: { label: string; href: string; variant?...` | Multiple CTA buttons rendered below the description (use instead of action for 2+ buttons) |
| `backgroundColor` | no | `string` | Background color for outer section |
| `textColor` | no | `string` | Text color for content |
| `backgroundImage` | no | `string` | Background image URL — creates a full-cover background with a subtle overlay |
| `action` | no | `{ label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }` | Optional CTA button rendered below the articles |

---

## `<Table />`
Table Component - Displays structured tabular data with optional search and filtering. Ideal for food menus, product catalogs, pricing tables, or any structured dataset.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional ID for anchor linking |
| `heading` | no | `string` | Section heading |
| `subheading` | no | `string` | Section subheading |
| `columns` | yes | `Array<{ label: string; key: string; }>` | Column headers |
| `rows` | yes | `Array<Record<string, string>>` | Table rows |
| `showSearch` | no | `boolean` | Whether to show a search bar above the table |
| `searchPlaceholder` | no | `string` | Placeholder text for the search bar |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class, e.g., 'bg-white') |
| `backgroundImage` | no | `string` | Background image URL for the outer section |
| `textColor` | no | `string` | Text color for headings and content (Tailwind class, e.g., 'text-white') |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'left' (default), 'center', or 'right' |
| `headerBackgroundColor` | no | `string` | Header background color (Tailwind class, e.g., 'bg-gray-100') |
| `rowHoverColor` | no | `string` | Hover row background color (Tailwind class) |
| `maxWidth` | no | `string` | Max width constraint (Tailwind class, e.g., 'max-w-4xl') |
| `card` | no | `boolean` | Card styling for the table |
| `cardBackgroundColor` | no | `string` | Card background color (Tailwind class) |

---

## `<Team />`
Team Component - Showcases key staff members or contributors. Use this to build trust and humanize the brand.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional ID for anchor linking |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class, e.g., 'bg-white') |
| `textColor` | no | `string` | Base text color for heading and body text (Tailwind class, e.g., 'text-white') |
| `align` | no | `'left' \| 'center' \| 'right'` | Horizontal alignment of the section header: 'center' (default), 'left', or 'right' |
| `columns` | no | `2 \| 3 \| 4` | Number of columns in the grid layout (2, 3, or 4; default: 4) |
| `heading` | no | `string` | Section heading |
| `subheading` | no | `string` | Supporting description |
| `members` | yes | `Array<{ name: string; role: string; bio?: string; avatar?: string; }>` | URL to the member's profile picture |

---

## `<Testimonials />`
Testimonials Component - Property-Driven Architecture

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links (e.g. href="#testimonials") |
| `heading` | no | `string` | — |
| `subheading` | no | `string` | Supporting description shown below the heading |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class, e.g. 'bg-white') |
| `textColor` | no | `string` | Base text color applied to heading and subheading (Tailwind class, e.g. 'text-white'). Use when backgroundColor is dark. |
| `headingColor` | no | `string` | Override color for the section heading only (Tailwind class, e.g. 'text-red-600'). Takes precedence over textColor for the h2 element. |
| `layout` | no | `'grid' \| 'split'` | Layout variant: 'grid' for card grid (default), 'split' for left-text right-image |
| `columns` | no | `2 \| 3 \| 4` | Number of columns in the card grid (default: 3). Only applies when layout='grid'. |
| `maxWidth` | no | `string` | Tailwind max-width class constraining the inner content container (e.g. 'max-w-2xl', 'max-w-4xl'). Defaults to 'max-w-7xl'. |
| `align` | no | `'left' \| 'center' \| 'right'` | Text alignment for heading and subheading: 'center' (default), 'left', or 'right' |
| `testimonials` | yes | `Array<{ quote: string; author: string; role?: string; avatar?: string; image?: { src: string; alt: string; }; }>` | — |

---

## `<TwoColumn />`
TwoColumn Component - A two-column layout with independent left and right content areas. Use this for side-by-side comparisons, dual messaging, or balanced layouts.

| Property | Required | Type | Description |
| :--- | :--- | :--- | :--- |
| `id` | no | `string` | Optional anchor id for in-page links |
| `logo` | no | `{ src: string; alt?: string; size?: string; }` | Optional logo image displayed centered above the two-column layout |
| `leftHeading` | no | `string` | Left column heading |
| `leftParagraphs` | no | `string[]` | Left column paragraphs |
| `leftImage` | no | `{ src: string; alt: string; }` | Left column image |
| `leftLinks` | no | `Array<{ label: string; href: string; }>` | Left column navigation links |
| `leftContent` | no | `Array<{ title?: string; description?: string; items?: Array<{ title: string; description?: string }>; form?: { fields: Array<{ label?: string; type: 'email' \| 'text' \| 'textarea'; placeholder: string }>, buttonLabel: ...` | Left column content sections (e.g., forms, cards with structured items) |
| `rightHeading` | no | `string` | Right column heading |
| `rightParagraphs` | no | `string[]` | Right column paragraphs |
| `rightImage` | no | `{ src: string; alt: string; }` | Right column image |
| `rightImages` | no | `Array<{ src: string; alt: string; }>` | Right column images for gallery grid |
| `rightContent` | no | `Array<{ title?: string; description?: string; items?: Array<{ title: string; description?: string }>; action?: { label: string; href: string; variant?: 'primary' \| 'secondary' \| 'success'; }; }>` | Right column content sections (e.g., cards with structured items) |
| `backgroundColor` | no | `string` | Background color for the outer section (Tailwind class) |
| `leftBackgroundColor` | no | `string` | Background color for the left column (Tailwind class); overrides backgroundColor for that column |
| `rightBackgroundColor` | no | `string` | Background color for the right column (Tailwind class); overrides backgroundColor for that column |
| `leftBackgroundImage` | no | `string` | Background image URL for the left column |
| `rightBackgroundImage` | no | `string` | Background image URL for the right column |
| `leftTextColor` | no | `string` | Text color for left column (Tailwind class) |
| `rightTextColor` | no | `string` | Text color for right column (Tailwind class) |
| `textColor` | no | `string` | Text color for content (Tailwind class) |
| `leftLinkColor` | no | `string` | Link color for left column navigation (Tailwind class) |
| `spacing` | no | `'normal' \| 'compact'` | Padding and spacing preset: 'normal' (default) or 'compact' |
