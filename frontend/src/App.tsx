import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Home from "./pages/Home";
import Explorer from "./pages/Explorer";
import OrderBook from "./pages/OrderBook";
import StrategyLab from "./pages/StrategyLab";
import Analytics from "./pages/Analytics";
import Sweep from "./pages/Sweep";
import UpDownLab from "./pages/UpDownLab";
import HDLab from "./pages/HDLab";
import Recorder from "./pages/Recorder";
import Learn from "./pages/Learn";
import TradingDisabled from "./pages/TradingDisabled";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/explorer" element={<Explorer />} />
        <Route path="/book" element={<OrderBook />} />
        <Route path="/lab" element={<StrategyLab />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/sweep" element={<Sweep />} />
        <Route path="/updown" element={<UpDownLab />} />
        <Route path="/hdlab" element={<HDLab />} />
        <Route path="/recorder" element={<Recorder />} />
        <Route path="/learn" element={<Learn />} />
        <Route path="/trading" element={<TradingDisabled />} />
      </Route>
    </Routes>
  );
}
