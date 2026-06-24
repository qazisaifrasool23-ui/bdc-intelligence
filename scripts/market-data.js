/* market-data.js
 * Free, no-key live market data for traded BDCs via Yahoo Finance with Stooq fallback.
 * Returns null gracefully on failure; never throws to the page.
 * No backend required — runs entirely in the browser.
 */
(function (global) {
  'use strict';

  // 60-second in-memory cache so re-renders don't re-fetch
  var _cache = {};
  var CACHE_MS = 60 * 1000;

  function _now() { return Date.now(); }

  function _cached(key) {
    var hit = _cache[key];
    if (hit && (_now() - hit.t) < CACHE_MS) return hit.v;
    return null;
  }
  function _store(key, v) { _cache[key] = { t: _now(), v: v }; return v; }

  /* Fetch with timeout. Returns parsed JSON or null. */
  function _fetchJSON(url, timeoutMs) {
    timeoutMs = timeoutMs || 6000;
    return new Promise(function (resolve) {
      var done = false;
      var to = setTimeout(function () { if (!done) { done = true; resolve(null); } }, timeoutMs);
      try {
        fetch(url, { mode: 'cors' })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (j) { if (!done) { done = true; clearTimeout(to); resolve(j); } })
          .catch(function () { if (!done) { done = true; clearTimeout(to); resolve(null); } });
      } catch (e) {
        if (!done) { done = true; clearTimeout(to); resolve(null); }
      }
    });
  }

  /* Fetch text (for Stooq CSV fallback). */
  function _fetchText(url, timeoutMs) {
    timeoutMs = timeoutMs || 6000;
    return new Promise(function (resolve) {
      var done = false;
      var to = setTimeout(function () { if (!done) { done = true; resolve(null); } }, timeoutMs);
      try {
        fetch(url, { mode: 'cors' })
          .then(function (r) { return r.ok ? r.text() : null; })
          .then(function (t) { if (!done) { done = true; clearTimeout(to); resolve(t); } })
          .catch(function () { if (!done) { done = true; clearTimeout(to); resolve(null); } });
      } catch (e) {
        if (!done) { done = true; clearTimeout(to); resolve(null); }
      }
    });
  }

  /* Yahoo: get quote summary for a ticker. Returns simplified object or null. */
  function _yahooQuote(ticker) {
    // Yahoo's chart endpoint is the most CORS-friendly. Use it with range=1d to get current price & day stats.
    var url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(ticker) +
              '?range=1d&interval=1d&includePrePost=false';
    return _fetchJSON(url).then(function (j) {
      try {
        if (!j || !j.chart || !j.chart.result || !j.chart.result[0]) return null;
        var r = j.chart.result[0];
        var meta = r.meta || {};
        return {
          price: meta.regularMarketPrice != null ? +meta.regularMarketPrice : null,
          previousClose: meta.chartPreviousClose != null ? +meta.chartPreviousClose : null,
          volume: meta.regularMarketVolume != null ? +meta.regularMarketVolume : null,
          fiftyTwoWeekHigh: meta.fiftyTwoWeekHigh != null ? +meta.fiftyTwoWeekHigh : null,
          fiftyTwoWeekLow: meta.fiftyTwoWeekLow != null ? +meta.fiftyTwoWeekLow : null,
          exchange: meta.exchangeName || null,
          currency: meta.currency || 'USD',
          source: 'yahoo',
          asOf: meta.regularMarketTime ? new Date(meta.regularMarketTime * 1000) : new Date()
        };
      } catch (e) { return null; }
    });
  }

  /* Stooq fallback: simple CSV with last price. Stooq tickers are lowercase with .us suffix for US stocks. */
  function _stooqQuote(ticker) {
    var st = ticker.toLowerCase() + '.us';
    var url = 'https://stooq.com/q/l/?s=' + encodeURIComponent(st) + '&i=d&f=sd2t2ohlcv';
    return _fetchText(url).then(function (t) {
      if (!t) return null;
      try {
        // CSV header line + data line
        var lines = t.trim().split('\n');
        if (lines.length < 2) return null;
        var cols = lines[1].split(',');
        // sd2t2ohlcv = symbol, date, time, open, high, low, close, volume
        if (cols.length < 8) return null;
        var close = parseFloat(cols[6]);
        var open = parseFloat(cols[3]);
        var high = parseFloat(cols[4]);
        var low = parseFloat(cols[5]);
        var vol = parseFloat(cols[7]);
        if (isNaN(close)) return null;
        return {
          price: close,
          previousClose: !isNaN(open) ? open : null,
          volume: !isNaN(vol) ? vol : null,
          fiftyTwoWeekHigh: null, fiftyTwoWeekLow: null,
          exchange: 'STOOQ', currency: 'USD',
          source: 'stooq',
          asOf: new Date()
        };
      } catch (e) { return null; }
    });
  }

  /* Public: fetch quote. Returns Promise<quote|null>. */
  function fetchQuote(ticker) {
    if (!ticker) return Promise.resolve(null);
    var key = 'q:' + ticker;
    var c = _cached(key);
    if (c) return Promise.resolve(c);
    return _yahooQuote(ticker).then(function (q) {
      if (q && q.price != null) return _store(key, q);
      return _stooqQuote(ticker).then(function (s) {
        return _store(key, s); // may be null
      });
    });
  }

  /* Yahoo: historical close prices. range: '1y','2y','5y','max'. interval: '1d','1wk','1mo'. */
  function _yahooHistory(ticker, range, interval) {
    range = range || '5y';
    interval = interval || '1mo';
    var url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(ticker) +
              '?range=' + range + '&interval=' + interval;
    return _fetchJSON(url).then(function (j) {
      try {
        if (!j || !j.chart || !j.chart.result || !j.chart.result[0]) return null;
        var r = j.chart.result[0];
        var ts = r.timestamp || [];
        var closes = (r.indicators && r.indicators.quote && r.indicators.quote[0] &&
                      r.indicators.quote[0].close) || [];
        var vols = (r.indicators && r.indicators.quote && r.indicators.quote[0] &&
                    r.indicators.quote[0].volume) || [];
        var out = [];
        for (var i = 0; i < ts.length; i++) {
          if (closes[i] == null) continue;
          var d = new Date(ts[i] * 1000);
          out.push({
            date: d.toISOString().slice(0, 10),
            close: +closes[i],
            volume: vols[i] != null ? +vols[i] : null
          });
        }
        return out.length ? out : null;
      } catch (e) { return null; }
    });
  }

  /* Public: fetch price history. Promise<[{date,close,volume},...] | null>. */
  function fetchHistory(ticker, range, interval) {
    if (!ticker) return Promise.resolve(null);
    var key = 'h:' + ticker + ':' + (range || '5y') + ':' + (interval || '1mo');
    var c = _cached(key);
    if (c) return Promise.resolve(c);
    return _yahooHistory(ticker, range, interval).then(function (h) {
      return _store(key, h);
    });
  }

  /* Compute derived metrics given quote + fund's database row. */
  function computeDerived(quote, fundLatest) {
    /* fundLatest expected fields: nav_per_share, shares_outstanding, dividend_per_share,
       net_investment_income_mn  — any may be null. */
    if (!quote || quote.price == null) return null;
    var d = { source: quote.source };
    var price = quote.price;

    if (fundLatest && fundLatest.nav_per_share != null && +fundLatest.nav_per_share > 0) {
      var nav = +fundLatest.nav_per_share;
      d.p_nav = +(price / nav).toFixed(3);
      d.price_discount = +(price - nav).toFixed(2);
    }

    if (fundLatest && fundLatest.shares_outstanding != null && +fundLatest.shares_outstanding > 0) {
      // shares_outstanding stored as a raw share count (units vary by fund); compute in millions of $
      d.market_cap_mn = +(price * +fundLatest.shares_outstanding / 1e6).toFixed(1);
    }

    if (fundLatest && fundLatest.dividend_per_share != null && +fundLatest.dividend_per_share > 0) {
      // dividend_per_share is quarterly; annualize ×4
      var annDPS = +fundLatest.dividend_per_share * 4;
      d.div_yield_mkt_pct = +((annDPS / price) * 100).toFixed(2);
    }

    if (fundLatest && fundLatest.net_investment_income_mn != null &&
        fundLatest.shares_outstanding != null && +fundLatest.shares_outstanding > 0) {
      // TTM-ish: latest quarter NII × 4, per share
      var niiPerShare = (+fundLatest.net_investment_income_mn * 1e6 * 4) / +fundLatest.shares_outstanding;
      if (niiPerShare > 0) d.p_nii = +(price / niiPerShare).toFixed(2);
    }

    return d;
  }

  /* Compute drawdown series from price history. Returns array of % below running max. */
  function computeDrawdownSeries(history) {
    if (!history || !history.length) return null;
    var peak = -Infinity;
    return history.map(function (h) {
      if (h.close > peak) peak = h.close;
      return { date: h.date, drawdown_pct: +(((h.close - peak) / peak) * 100).toFixed(2) };
    });
  }

  /* Compute max drawdown. */
  function computeMaxDrawdown(history) {
    var dd = computeDrawdownSeries(history);
    if (!dd || !dd.length) return null;
    return dd.reduce(function (m, p) { return p.drawdown_pct < m ? p.drawdown_pct : m; }, 0);
  }

  global.BDCMarketData = {
    fetchQuote: fetchQuote,
    fetchHistory: fetchHistory,
    computeDerived: computeDerived,
    computeDrawdownSeries: computeDrawdownSeries,
    computeMaxDrawdown: computeMaxDrawdown
  };
})(window);
