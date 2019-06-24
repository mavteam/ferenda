$(document).ready(function () {
    /* hook up the offcanvas classes to make a sliding left menu
     * possible on small screens  */
    $('.slidebutton').on("click touchstart", function(e) {
	$('.row-offcanvas').toggleClass('active');
	e.preventDefault();
    });
    /* clicking the search button (only visible on mobile) should show
     * the search field (and not submit the search yet) if not already
     * shown. */
    $('form#search button').on("click touchstart", function(e) {
	form = $(this).closest("form");
	if (!form.hasClass("active")) {
	    $('a.navbar-brand').addClass("hidden-xs");
	    $('button.navbar-toggle').addClass("hidden-xs");
	    form.addClass("active");
	    $('input').focus();
	    e.preventDefault(); /* if it's a touchstart event, cancel the following click event */
	    return false; /* don't submit the form yet */
	}
    });

  $('form#search button').mousedown(function() {
    if (form.hasClass("active")) {
      form.submit();
    }
  });
				    
  /* search field should auto-hide when it looses focus (again, on
   * mobile). One problem though: Clicking the button makes it lose
   * focus. We therefore also register a mousedown handler (which
   * fires before blur) above */
  $('form#search input').blur(function(e) {
    $(this).closest("form").removeClass("active");
    $('a.navbar-brand').removeClass("hidden-xs");
    $('button.navbar-toggle').removeClass("hidden-xs");
    return true;
  });
  /* pressing enter in search field should submit the form. Maybe it
   * always does this? */
  /*
  $('form#search input').keypress(function(e) {
    if(e.which == 13){
      $(this).closest("form").submit();
    }
  });
  */
  /* this is said to work in situations where doc.body doesn't... */
  body = document.getElementsByTagName('body')[0];
  
  /* functions for replacing the text rendering of a pdf page with an
   * image rendering of same */
    $('div.sida a.view-img').on("click touchstart", function () {
	/* hide everything else from here to next page */
	$(this).parents("div.sida").nextUntil("div.sida").hide()

	/* if we haven't reached a pagebreak, we might need to
	 * continue hiding elements in the next top-level div */
	if ($(this).parents("div.sida").siblings("div.sida").length == 0) {
	    nextsectionstart = $(this).parents("div.toplevel").next().find("section *").first();
	    nextsectionstart.hide();
	    nextsectionstart.nextUntil("div.sida").hide();
	    /* FIXME: There might be two top-level sections on a page... */
	}
	navtabs = $(this).parents("ul")

	navtabs.find("li:nth-child(1)").removeClass("active");
	navtabs.find("li:nth-child(2)").addClass("active");
	/* on-demand load facsimileimage and show */
        navtabs.siblings(".facsimile").children("img").each(function(idx) {
           this.src = $(this).attr('data-src');
           $(this).show();
	})
    });
    $('div.sida a.view-text').on("click touchstart", function() {
	navtabs = $(this).parents("ul")
	navtabs.find("li:nth-child(1)").addClass("active");
	navtabs.find("li:nth-child(2)").removeClass("active");
        navtabs.siblings(".facsimile").children("img").hide();
	$(this).parents("div.sida").nextUntil("div.sida").show();
	if ($(this).parents("div.sida").siblings("div.sida").length == 0) {
	    nextsectionstart = $(this).parents("div.toplevel").next().find("section *").first();
	    nextsectionstart.show();
	    nextsectionstart.nextUntil("div.sida").show();
	}
    });

  /* hook up the autocomplete function of the search field */				
  var suggestions = new Bloodhound({
    datumTokenizer: Bloodhound.tokenizers.obj.whitespace('label'),
    queryTokenizer: Bloodhound.tokenizers.whitespace,
    /*
    prefetch: {
      url: '/rsrc/api/suggestions.json',
      cache: false
    },
    */
    remote: {
      url: '/api/?q=%QUERY&_ac=true',
      wildcard: '%QUERY'
    } 
  });
  promise = suggestions.initialize();
  promise
    .done(function() {
      console.log('ready to go!');
    })
    .fail(function() {
      console.log('err, something went wrong :(');
    });
  $('.navbar-form .typeahead').typeahead(null, {
    name: 'suggestions',
    highlight: true,
    display: 'comment',
    source: suggestions,
    minLength: 1,
    templates: {
      suggestion: function(ctx) {
	// typeahead.js should be able to highlight matches itself,
	// but I can't get it to work, so we do it manually.
        q_regex = new RegExp(ctx._query.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&'), 'ig');
        ctx.comment = ctx.comment.replace(q_regex, "<strong>$&</strong>");
        if (ctx.role == "expired") {
          ctx.comment = "[upphävd] " + ctx.comment;
        }
        return "<div class='tt-suggestion'>" + ctx.comment + "<br/><small>" + ctx.desc + "</small></div>";
      }
    },
    limit: 9
  });
  $('.navbar-form .typeahead').bind('typeahead:select', function(ev, suggestion) {
     window.location.href=suggestion.url
  });

  /* Functionality to show streaming logs for long-running commands */
  output = $('#streaming-log-output');
  if (output.length > 0) {
      // console.log("Setting up ajax call to stream log output")
      connection = $.ajax({
	  cache: false,
	  dataType: 'text',
	  url: output.first().attr('src'),
	  xhrFields: {
	      onprogress: function(e) {
		  // console.log('onprogress: response len is ' + e.currentTarget.response.length);
		  output.text(e.currentTarget.response);
	      }
	  }
      });
      connection.done(function(data) {
          // console.log('Complete response = ' + data);
	  output.text(data);
      });

  }
})



