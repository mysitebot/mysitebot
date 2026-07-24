// The MDX component map. Both the page route ([...slug].astro) and the post
// route (blog/[slug].astro) render agent-authored MDX, and both must offer the
// same sections — keeping the map here stops the two drifting apart.
import Hero from './Hero.astro';
import ContactForm from './ContactForm.astro';
import Pricing from './Pricing.astro';
import Gallery from './Gallery.astro';
import Testimonials from './Testimonials.astro';
import Features from './Features.astro';
import Newsletter from './Newsletter.astro';
import Team from './Team.astro';
import ListingGrid from './ListingGrid.astro';
import Banner from './Banner.astro';
import BlogList from './BlogList.astro';
import Calendar from './Calendar.astro';
import Navbar from './Navbar.astro';
import HeroCarousel from './HeroCarousel.astro';
import Footer from './Footer.astro';
import Article from './Article.astro';
import Header from './Header.astro';
import Sidebar from './Sidebar.astro';
import TwoColumn from './TwoColumn.astro';
import NewsGrid from './NewsGrid.astro';
import Parallax from './Parallax.astro';
import Table from './Table.astro';
import FAQ from './FAQ.astro';
import Stats from './Stats.astro';
import LogoCloud from './LogoCloud.astro';

export const sectionComponents = {
  Hero, ContactForm, Pricing, Gallery, Testimonials, Features, Newsletter,
  Team, ListingGrid, Banner, BlogList, Calendar, Navbar, HeroCarousel, Footer,
  Article, Header, Sidebar, TwoColumn, NewsGrid, Parallax, Table, FAQ, Stats,
  LogoCloud,
};
