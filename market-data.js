/* market-data.js v2
 * Free, no-key live market data for traded BDCs.
 * Tries: corsproxy.io -> allorigins.win -> direct Yahoo -> Stooq -> null.
 * Caches 60 seconds. Never throws. Returns null gracefully on total failure.
 */
(function (global) {
  'use strict';

  var _cache = {};
  var CACHE_MS = 60 * 1000;
  function _now() { return Date.now(); }
  function _cached(key) {
    var hit = _cache[key];
    return (hit && (_now() - hit.t) < CACHE_MS) ? hit.v : null;
  }
  function _store(key, v) { _cache[key] = { t: _now(), v: v }; return v; }

  /* Wrap a URL in a CORS-proxy. Returns array of attempts in order. */
  function _proxies(target) {
    return [
      'https://corsproxy.io/?' + encodeURIComponent(target),
      'https://api.allorigins.win/raw?url=' + encodeURIComponent(target),
      target  /* direct, in case it works */
    ];
  }

  function _fetchTimeout(url, asText, timeoutMs) {
    timeoutMs = timeoutMs || 8000;
    return new Promise(function (resolve) {
      var done = false;
      var to = setTimeout(function () { if (!done) { done = true; resolve(null); } }, timeoutMs);
      try {
        fetch(url, { mode: 'cors' })
          .then(function (r) {
            if (!r || !r.ok) return null;
            return asText ? r.text() : r.json();
          })
          .then(function (data) {
            if (!done) { done = true; clearTimeout(to); resolve(data); }
          })
          .catch(function () { if (!done) { done = true; clearTimeout(to); resolve(null); } });
      } catch (e) {
        if (!done) { done = true; clearTimeout(to); resolve(null); }
      }
    });
  }

  function _tryProxies(target, asText) {
    var urls = _proxies(target);
    var i = 0;
    function next() {
      if (i >= urls.length) return Promise.resolve(null);
      return _fetchTimeout(urls[i++], asText).then(function (r) {
        if (r) return r;
        return next();
      });
    }
    return next();
  }

  function _yahooQuote(ticker) {
    var target = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(ticker) +
                 '?range=1d&interval=1d&includePrePost=false';
    return _tryProxies(target, false).then(function (j) {
      try {
        if (!j || !j.chart || !j.chart.result || !j.chart.result[0]) return null;
        var r = j.chart.result[0];
        var meta = r.meta || {};
        if (meta.regularMarketPrice == null) return null;
        return {
          price: +meta.regularMarketPrice,
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

  function _stooqQuote(ticker) {
    var target = 'https://stooq.com/q/l/?s=' + encodeURIComponent(ticker.toLowerCase() + '.us') +
                 '&i=d&f=sd2t2ohlcv';
    return _tryProxies(target, true).then(function (t) {
      if (!t) return null;
      try {
        var lines = t.trim().split('\n');
        if (lines.length < 2) return null;
        var cols = lines[1].split(',');
        if (cols.length < 8) return null;
        var close = parseFloat(cols[6]);
        if (isNaN(close)) return null;
        var open = parseFloat(cols[3]);
        var high = parseFloat(cols[4]);
        var low = parseFloat(cols[5]);
        var vol = parseFloat(cols[7]);
        return {
          price: close,
          previousClose: !isNaN(open) ? open : null,
          volume: !isNaN(vol) ? vol : null,
          fiftyTwoWeekHigh: null,
          fiftyTwoWeekLow: null,
          exchange: 'STOOQ',
          currency: 'USD',
          source: 'stooq',
          asOf: new Date()
        };
      } catch (e) { return null; }
    });
  }

  function fetchQuote(ticker) {
    if (!ticker) return Promise.resolve(null);
    var key = 'q:' + ticker;
    var c = _cached(key);
    if (c) return Promise.resolve(c);
    return _yahooQuote(ticker).then(function (q) {
      if (q && q.price != null) return _store(key, q);
      return _stooqQuote(ticker).then(function (s) { return _store(key, s); });
    });
  }

  function _yahooHistory(ticker, range, interval) {
    range = range || '5y'; interval = interval || '1mo';
    var target = 'https://query1.finance.yahoo.com/v8/finance/chart/' + encodeURIComponent(ticker) +
                 '?range=' + range + '&interval=' + interval;
    return _tryProxies(target, false).then(function (j) {
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
          out.push({
            date: new Date(ts[i] * 1000).toISOString().slice(0, 10),
            close: +closes[i],
            volume: vols[i] != null ? +vols[i] : null
          });
        }
        return out.length ? out : null;
      } catch (e) { return null; }
    });
  }

  function fetchHistory(ticker, range, interval) {
    if (!ticker) return Promise.resolve(null);
    var key = 'h:' + ticker + ':' + (range || '5y') + ':' + (interval || '1mo');
    var c = _cached(key);
    if (c) return Promise.resolve(c);
    return _yahooHistory(ticker, range, interval).then(function (h) { return _store(key, h); });
  }

  function computeDerived(quote, fundLatest) {
    if (!quote || quote.price == null) return null;
    var d = { source: quote.source };
    var price = quote.price;

    if (fundLatest && fundLatest.nav_per_share != null && +fundLatest.nav_per_share > 0) {
      var nav = +fundLatest.nav_per_share;
      d.p_nav = +(price / nav).toFixed(3);
      d.price_discount = +(price - nav).toFixed(2);
    }
    if (fundLatest && fundLatest.shares_outstanding != null && +fundLatest.shares_outstanding > 0) {
      d.market_cap_mn = +(price * +fundLatest.shares_outstanding / 1e6).toFixed(1);
    }
    if (fundLatest && fundLatest.dividend_per_share != null && +fundLatest.dividend_per_share > 0) {
      var annDPS = +fundLatest.dividend_per_share * 4;
      d.div_yield_mkt_pct = +((annDPS / price) * 100).toFixed(2);
    }
    if (fundLatest && fundLatest.net_investment_income_mn != null &&
        fundLatest.shares_outstanding != null && +fundLatest.shares_outstanding > 0) {
      var niiPerShare = (+fundLatest.net_investment_income_mn * 1e6 * 4) / +fundLatest.shares_outstanding;
      if (niiPerShare > 0) d.p_nii = +(price / niiPerShare).toFixed(2);
    }
    return d;
  }

  function computeDrawdownSeries(history) {
    if (!history || !history.length) return null;
    var peak = -Infinity;
    return history.map(function (h) {
      if (h.close > peak) peak = h.close;
      return { date: h.date, drawdown_pct: +(((h.close - peak) / peak) * 100).toFixed(2) };
    });
  }

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
