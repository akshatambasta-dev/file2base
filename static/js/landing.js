(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Recreate the geometric block-letter mark used by the original Lovable intro.
  const glyphs = {
    F: ['11111', '10000', '10000', '11110', '10000', '10000', '10000'],
    I: ['11111', '00100', '00100', '00100', '00100', '00100', '11111'],
    L: ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
    E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
    '2': ['11110', '00001', '00001', '01110', '10000', '10000', '11111'],
    B: ['11110', '10001', '10001', '11110', '10001', '10001', '11110'],
    A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
    S: ['01111', '10000', '10000', '01110', '00001', '00001', '11110'],
  };
  const svgNS = 'http://www.w3.org/2000/svg';
  document.body.classList.add('lp-motion-enabled');

  function buildBlockWordmark(svg, animated) {
    if (!svg || svg.dataset.generated === 'true') {
      if (svg && animated) svg.querySelectorAll('.lp-block-cell').forEach((cell) => cell.classList.add('is-animated'));
      return;
    }
    const text = 'FILE2BASE';
    let offset = 0;
    const cells = [];
    [...text].forEach((character, letterIndex) => {
      const glyph = glyphs[character];
      if (!glyph) return;
      glyph.forEach((row, y) => [...row].forEach((bit, x) => {
        if (bit !== '1') return;
        const seed = Math.sin((letterIndex + 1) * 12.9898 + x * 78.233 + y * 37.719) * 43758.5453;
        const random = seed - Math.floor(seed);
        cells.push({ x: offset + x, y, delay: letterIndex * 90 + random * 500, accent: letterIndex === 4 });
      }));
      offset += 6;
    });
    svg.setAttribute('viewBox', `0 0 ${offset - 1} 7`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('shape-rendering', 'crispEdges');
    svg.replaceChildren();
    cells.forEach((cell) => {
      const rect = document.createElementNS(svgNS, 'rect');
      rect.setAttribute('x', cell.x);
      rect.setAttribute('y', cell.y);
      rect.setAttribute('width', '1.02');
      rect.setAttribute('height', '1.02');
      rect.setAttribute('class', `lp-block-cell${cell.accent ? ' is-accent' : ''}${animated ? ' is-animated' : ''}`);
      rect.style.animationDelay = `${cell.delay}ms`;
      svg.appendChild(rect);
    });
    svg.dataset.generated = 'true';
  }

  const introScreen = document.getElementById('lp-intro-screen');
  const introWordmark = document.querySelector('[data-wordmark="intro"]');
  const heroWordmark = document.querySelector('[data-wordmark="hero"]');
  buildBlockWordmark(introWordmark, !reduceMotion);
  buildBlockWordmark(heroWordmark, false);

  let introExitTimer = null;
  let introGoneTimer = null;
  let introExited = false;
  function exitIntro() {
    if (!introScreen || introExited) return;
    introExited = true;
    window.clearTimeout(introExitTimer);
    introScreen.classList.add('is-exiting');
    window.removeEventListener('keydown', onIntroKey);
    introGoneTimer = window.setTimeout(() => {
      introScreen.classList.add('is-gone');
      introScreen.setAttribute('aria-hidden', 'true');
    }, 1100);
  }
  function onIntroKey(event) {
    if (event.key === 'Tab') return;
    exitIntro();
  }
  if (introScreen) {
    if (reduceMotion) {
      introScreen.classList.add('is-gone');
      introScreen.setAttribute('aria-hidden', 'true');
      introExited = true;
    } else {
      introScreen.addEventListener('click', exitIntro);
      introScreen.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          exitIntro();
        }
      });
      window.addEventListener('keydown', onIntroKey);
      introExitTimer = window.setTimeout(exitIntro, 2300);
    }
  }
  if (heroWordmark) {
    const revealHeroMark = () => {
      if (reduceMotion) {
        heroWordmark.classList.add('is-ready');
        return;
      }
      buildBlockWordmark(heroWordmark, true);
      heroWordmark.classList.add('is-ready');
    };
    if (reduceMotion) revealHeroMark();
    else window.setTimeout(revealHeroMark, 2600);
  }

  // Fine-pointer desktop users get the small tracking square from the design.
  const customCursor = document.getElementById('lp-custom-cursor');
  if (customCursor && !reduceMotion && window.matchMedia('(pointer: fine)').matches) {
    window.addEventListener('mousemove', (event) => {
      const target = event.target instanceof Element ? event.target.closest('button, a, [tabindex], input, select, textarea') : null;
      customCursor.style.transform = `translate(${event.clientX}px, ${event.clientY}px) translate(-50%,-50%) scale(${target ? 2.4 : 1})`;
      customCursor.classList.toggle('is-hovering', Boolean(target));
      customCursor.classList.add('is-visible');
    }, { passive: true });
    document.addEventListener('mouseleave', () => customCursor.classList.remove('is-visible'));
    document.addEventListener('mouseenter', () => customCursor.classList.add('is-visible'));
  }

  // Add the original in-view choreography to the content blocks, not just the hero.
  const staggeredElements = document.querySelectorAll(
    '.lp-problem-list li, .lp-solution-step, .lp-step-button, .lp-customer-grid article, .lp-mvp-grid > div, .lp-roadmap-line li, .lp-accordion-item'
  );
  staggeredElements.forEach((element, index) => {
    element.classList.add('lp-motion-reveal');
    element.style.transitionDelay = `${(index % 6) * 70}ms`;
  });
  document.querySelectorAll('.lp-section-heading h2').forEach((heading) => heading.classList.add('lp-motion-mask'));
  const sections = ['top', 'problem', 'solution', 'how', 'concept', 'engine', 'customers', 'mvp', 'roadmap', 'vision'];
  const progress = document.getElementById('page-progress');
  const counter = document.getElementById('section-counter');
  const navLinks = Array.from(document.querySelectorAll('.lp-nav-links [data-section]'));

  const updateScrollUI = () => {
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
    if (progress) progress.style.width = `${maxScroll > 0 ? (window.scrollY / maxScroll) * 100 : 0}%`;
    let active = 0;
    sections.forEach((id, index) => {
      const element = document.getElementById(id);
      if (element && element.getBoundingClientRect().top < window.innerHeight * 0.42) active = index;
    });
    if (counter) counter.textContent = `${String(active).padStart(2, '0')} / 09`;
    document.querySelectorAll('.lp-scrollword').forEach((word) => {
      const rect = word.getBoundingClientRect();
      const progress = Math.min(1, Math.max(0, (window.innerHeight - rect.top) / (window.innerHeight + rect.height)));
      word.style.transform = `translateX(${(0.5 - progress) * 40}%)`;
    });
    navLinks.forEach((link) => {
      const isActive = link.dataset.section === sections[active];
      link.classList.toggle('is-active', isActive);
      if (isActive) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  };
  window.addEventListener('scroll', updateScrollUI, { passive: true });
  window.addEventListener('resize', updateScrollUI);
  updateScrollUI();

  const revealElements = document.querySelectorAll('.reveal, .lp-motion-reveal, .lp-motion-mask');
  if ('IntersectionObserver' in window && !reduceMotion) {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    revealElements.forEach((el) => revealObserver.observe(el));
  } else {
    revealElements.forEach((el) => el.classList.add('in'));
  }

  const toggle = document.getElementById('nav-toggle');
  const mobileMenu = document.getElementById('mobile-menu');
  if (toggle && mobileMenu) {
    toggle.addEventListener('click', () => {
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? 'Close' : 'Index';
      mobileMenu.hidden = !open;
    });
    mobileMenu.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
      mobileMenu.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      toggle.textContent = 'Index';
    }));
  }

  const stepData = Array.from(document.querySelectorAll('.lp-step-button')).map((button) => ({
    button,
    number: button.querySelector('b')?.textContent || '01',
    title: button.querySelector('strong')?.textContent || '',
    description: button.querySelector('small')?.textContent || '',
  }));
  const activeStepNumber = document.getElementById('active-step-number');
  const activeStepTitle = document.getElementById('active-step-title');
  const activeStepDescription = document.getElementById('active-step-description');
  const activeStepProgress = document.getElementById('active-step-progress');
  const setStep = (index) => {
    const item = stepData[index];
    if (!item) return;
    stepData.forEach((step, i) => {
      step.button.classList.toggle('is-active', i === index);
      step.button.setAttribute('aria-pressed', String(i === index));
    });
    if (activeStepNumber) activeStepNumber.textContent = item.number;
    if (activeStepTitle) activeStepTitle.textContent = item.title;
    if (activeStepDescription) activeStepDescription.textContent = item.description;
    if (activeStepProgress) activeStepProgress.style.width = `${((index + 1) / stepData.length) * 100}%`;
  };
  stepData.forEach((item, index) => {
    item.button.addEventListener('click', () => setStep(index));
    item.button.addEventListener('mouseenter', () => setStep(index));
    item.button.addEventListener('focus', () => setStep(index));
  });

  const canvas = document.getElementById('schema-canvas');
  const stageTabs = Array.from(document.querySelectorAll('[data-stage]'));
  const stageButtons = stageTabs.filter((element) => element.tagName === 'BUTTON');
  let replayTimer = null;
  const setSchemaStage = (stage) => {
    if (!canvas) return;
    const normalized = Math.max(0, Math.min(4, Number(stage) || 0));
    canvas.dataset.stage = String(normalized);
    stageButtons.forEach((button) => button.setAttribute('aria-selected', String(Number(button.dataset.stage) === normalized)));
  };
  stageButtons.forEach((button) => button.addEventListener('click', () => {
    if (replayTimer) window.clearInterval(replayTimer);
    replayTimer = null;
    setSchemaStage(button.dataset.stage);
  }));
  if (canvas) {
    const entities = Array.from(canvas.querySelectorAll('.lp-entity'));
    const connected = {
      customers: ['customers-sales'],
      sales: ['customers-sales', 'sales-products'],
      products: ['sales-products', 'products-suppliers'],
      suppliers: ['products-suppliers'],
    };
    entities.forEach((entity) => {
      const activate = () => {
        canvas.dataset.hover = entity.dataset.entity || '';
        const hover = canvas.dataset.hover;
        const paths = Array.from(canvas.querySelectorAll('.lp-schema-lines path'));
        paths.forEach((path, index) => {
          const rel = ['customers-sales', 'sales-products', 'products-suppliers'][index];
          path.style.opacity = !hover || (connected[hover] || []).includes(rel) ? '' : '0.12';
        });
      };
      const deactivate = () => {
        delete canvas.dataset.hover;
        canvas.querySelectorAll('.lp-schema-lines path').forEach((path) => { path.style.opacity = ''; });
      };
      entity.addEventListener('mouseenter', activate);
      entity.addEventListener('focusin', activate);
      entity.addEventListener('mouseleave', deactivate);
      entity.addEventListener('focusout', deactivate);
      entity.setAttribute('tabindex', '0');
      entity.setAttribute('role', 'group');
      entity.setAttribute('aria-label', `${entity.querySelector('.lp-entity-name')?.textContent || entity.querySelector('.lp-source-name')?.textContent || 'Data entity'} and its fields`);
    });
  }

  const replayButton = document.getElementById('schema-replay');
  if (replayButton) replayButton.addEventListener('click', () => {
    if (replayTimer) window.clearInterval(replayTimer);
    let stage = 0;
    setSchemaStage(stage);
    replayTimer = window.setInterval(() => {
      stage += 1;
      setSchemaStage(stage);
      if (stage >= 4) {
        window.clearInterval(replayTimer);
        replayTimer = null;
      }
    }, reduceMotion ? 120 : 700);
  });

  document.querySelectorAll('.lp-accordion-item > button').forEach((button) => button.addEventListener('click', () => {
    const item = button.closest('.lp-accordion-item');
    if (!item) return;
    const open = !item.classList.contains('is-open');
    document.querySelectorAll('.lp-accordion-item').forEach((other) => {
      other.classList.remove('is-open');
      const control = other.querySelector(':scope > button');
      if (control) {
        control.setAttribute('aria-expanded', 'false');
        const marker = control.querySelector('span');
        if (marker) marker.textContent = '+';
      }
    });
    if (open) {
      item.classList.add('is-open');
      button.setAttribute('aria-expanded', 'true');
      const marker = button.querySelector('span');
      if (marker) marker.textContent = '−';
    }
  }));

  // Allow keyboard users to navigate sections without interfering with form input.
  window.addEventListener('keydown', (event) => {
    const target = event.target;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || event.ctrlKey || event.metaKey || event.altKey) return;
    if (!['n', 'p', '[', ']'].includes(event.key)) return;
    let active = 0;
    sections.forEach((id, index) => {
      const element = document.getElementById(id);
      if (element && element.getBoundingClientRect().top < window.innerHeight * 0.42) active = index;
    });
    const next = event.key === 'n' || event.key === ']' ? Math.min(sections.length - 1, active + 1) : Math.max(0, active - 1);
    document.getElementById(sections[next])?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' });
  });
})();
