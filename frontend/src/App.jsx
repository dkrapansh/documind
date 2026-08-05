import { ThemeProvider } from "./context/ThemeContext";
import { AuthProvider } from "./context/AuthContext";
import { Nav } from "./components/Nav";
import { Hero } from "./components/Hero";
import { Funnel } from "./components/Funnel";
import { Refusal } from "./components/Refusal";
import { Demo } from "./components/Demo";
import { Footer } from "./components/Footer";

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Nav />
        <Hero />
        <Funnel />
        <Refusal />
        <Demo />
        <Footer />
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
