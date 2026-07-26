import { ThemeProvider } from "./context/ThemeContext";
import { Nav } from "./components/Nav";
import { Hero } from "./components/Hero";
import { Funnel } from "./components/Funnel";
import { Refusal } from "./components/Refusal";
import { Demo } from "./components/Demo";
import { Footer } from "./components/Footer";

function App() {
  return (
    <ThemeProvider>
      <Nav />
      <Hero />
      <Funnel />
      <Refusal />
      <Demo />
      <Footer />
    </ThemeProvider>
  );
}

export default App;
