import sublime, sublime_plugin
import re
import time
try:
    # Python 3.x
    from . import context
    from .salesforce.metadata import metadata
except:
    # Python 2.x
    import context
    from salesforce.metadata import metadata

class SobjectCompletions(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        if not view.match_selector(locations[0], "source.java"):
            return []

        # Load sobjects compoletions
        setting = sublime.load_settings("sobjects_completion.sublime-settings")

        # Load sobjects field meatadata
        toolingapi_settings = context.get_toolingapi_settings()
        username = toolingapi_settings["username"]

        # If current username is in settings, it means project is initiated
        if not setting.has(username):
            return

        location = locations[0]
        pt = locations[0] - len(prefix) - 1
        ch = view.substr(sublime.Region(pt, pt + 1))

        if ch != ".":
            return

        # Get the variable name
        pt = pt - 1
        variable_name = view.substr(view.word(pt))

        # Get the matched region by variable name
        matched_regions = view.find_all("\\w+\\s+" + variable_name + "\\s*[;=]")
        matched_block = view.substr(matched_regions[0])
        if len(matched_block) == 0: return

        # Get the matched variable type
        sobject = matched_block.split(" ")[0]

        # If username is in settings, get the sobject fields describe dict
        metadata = setting.get(username)
        completion_list = []
        if sobject in metadata:
            fields = metadata.get(sobject)
        elif sobject.lower().capitalize() in metadata:
            fields = metadata.get(sobject.lower().capitalize())
        else: 
            return

        for key in fields.keys():
            completion_list.append((sobject + "." + key, fields[key]))

        return (completion_list, sublime.INHIBIT_WORD_COMPLETIONS or sublime.INHIBIT_EXPLICIT_COMPLETIONS)

# class ApexCompletions(sublime_plugin.EventListener):
#     def on_query_completions(self, view, prefix, locations):
#         if not view.match_selector(locations[0], "source.java"):
#             return []

#         completion_list = []
#         if prefix in metadata:
#             metadata_key = metadata[prefix]
#             for key in metadata_key.keys():
#                 print (key)
#                 completion_list.append((key, metadata_key[key]))

#         return (completion_list, sublime.INHIBIT_WORD_COMPLETIONS or sublime.INHIBIT_EXPLICIT_COMPLETIONS)

# Extends Sublime Text autocompletion to find matches in all open
# files. By default, Sublime only considers words from the current file.

# limits to prevent bogging down the system
MIN_WORD_SIZE = 3
MAX_WORD_SIZE = 30

MAX_VIEWS = 20
MAX_WORDS_PER_VIEW = 100
MAX_FIX_TIME_SECS_PER_VIEW = 0.01

class CrossViewCompletions(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        words = []

        # Limit number of views but always include the active view. This
        # view goes first to prioritize matches close to cursor position.
        other_views = [v for v in sublime.active_window().views() if v.id != view.id]
        views = [view] + other_views
        views = views[0:MAX_VIEWS]

        for v in views:
            if len(locations) > 0 and v.id == view.id:
                view_words = v.extract_completions(prefix, locations[0])
            else:
                view_words = v.extract_completions(prefix)

            view_words = [w for w in view_words]
            view_words = self.filter_words(view_words)
            view_words = self.fix_truncation(v, view_words)
            words += view_words

        words = self.without_duplicates(words)
        matches = [(w, w) for w in words]
        return matches

    def filter_words(self, words):
        words = words[0:MAX_WORDS_PER_VIEW]
        return [w for w in words if MIN_WORD_SIZE <= len(w) <= MAX_WORD_SIZE]

    # keeps first instance of every word and retains the original order
    # (n^2 but should not be a problem as len(words) <= MAX_VIEWS*MAX_WORDS_PER_VIEW)
    def without_duplicates(self, words):
        result = []
        for w in words:
            if w not in result:
                result.append(w)
        return result


    # Ugly workaround for truncation bug in Sublime when using view.extract_completions()
    # in some types of files.
    def fix_truncation(self, view, words):
        fixed_words = []
        start_time = time.time()

        for i, w in enumerate(words):
            #The word is truncated if and only if it cannot be found with a word boundary before and after

            # this fails to match strings with trailing non-alpha chars, like
            # 'foo?' or 'bar!', which are common for instance in Ruby.
            truncated = view.find(r'\b' + re.escape(w) + r'\b', 0) is None
            if truncated:
                #Truncation is always by a single character, so we extend the word by one word character before a word boundary
                extended_words = []
                view.find_all(r'\b' + re.escape(w) + r'\w\b', 0, "$0", extended_words)
                if len(extended_words) > 0:
                    fixed_words += extended_words
                else:
                    # to compensate for the missing match problem mentioned above, just
                    # use the old word if we didn't find any extended matches
                    fixed_words.append(w)
            else:
                #Pass through non-truncated words
                fixed_words.append(w)

            # if too much time is spent in here, bail out,
            # and don't bother fixing the remaining words
            if time.time() - start_time > MAX_FIX_TIME_SECS_PER_VIEW:
                return fixed_words + words[i+1:]

        return fixed_words

# Provide completions that match just after typing an opening angle bracket
# https://github.com/jairzh/sublime-sfdc-assist/blob/master/visualforce_completions.py
class PageCompletions(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        # Only trigger within HTML
        if not view.match_selector(locations[0],
                "text.html - source"):
            return []

        pt = locations[0] - len(prefix) - 1
        ch = view.substr(sublime.Region(pt, pt + 1))
        if ch != '<':
            return []

        # Not include chart component
        return ([
            ('apex:actionFunction\tVF', 'apex:actionFunction name="$1" action="$2" rerender="$3" status="$4"/>'),
            ('apex:actionPoller\tVF', 'apex:actionPoller action="$1" rerender="$2" interval="$3"/>'),
            ('apex:actionRegion\tVF', 'apex:actionRegion>\n\t$1\n</apex:actionRegion>'),
            ('apex:actionStatus\tVF', 'apex:actionStatus id="$1"/>'),
            ('apex:actionSupport\tVF', 'apex:actionSupport event="$1" action="$2" rerender="$3" status="$4"/>'),
            ('apex:attribute\tVF', 'apex:attribute name="$1" description="$2" type="$3" required=\"${4:true}\"/>'),
            ('apex:column\tVF', 'apex:column value="$1"/>'),
            ('apex:commandButton\tVF', 'apex:commandButton action="$1" value="$2" id="$3"/>'),
            ('apex:commandLink\tVF', 'apex:commandLink action="$1" value="$2" id="$3"/>'),
            ('apex:component\tVF', 'apex:component>\n\t$1\n</apex:component>'),
            ('apex:componentBody\tVF', 'apex:componentBody />'),
            ('apex:composition\tVF', 'apex:composition template="$1">\n\t$2\n</apex:composition>'),
            ('apex:dataList\tVF', 'apex:dataList value="$1" var="$2" id="$3">\n\t$4\n</apex:dataList>'),
            ('apex:dataTable\tVF', 'apex:dataTable value="$1" var="$2" id="$3">\n\t$4\n</apex:dataTable>'),
            ('apex:define\tVF', 'apex:define name="$1"/>'),
            ('apex:detail\tVF', 'apex:detail subject="$1" relatedList=\"${2:false}\" title=\"${3:false}\"/>'),
            ('apex:dynamicComponent\tVF', 'apex:dynamicComponent componentValue="$1"/>'),
            ('apex:emailPublisher\tVF', 'apex:emailPublisher />'),
            ('apex:enhancedList\tVF', 'apex:enhancedList type="$1" height="$2" rowsPerPage="$3" id="$4"/>'),
            ('apex:facet\tVF', 'apex:facet name="$1">$2<apex:facet/>'),
            ('apex:flash\tVF', 'apex:flash src="$1" height="$2" width="$3"/>'),
            ('apex:form\tVF', 'apex:form id="$1">\n\t$2\n</apex:form>'),
            ('apex:iframe\tVF', 'apex:iframe src="$1" scrolling="$2" id="$3"/>'),
            ('apex:image\tVF', 'apex:image id="$1" value="$2" width="$3" height="$4"/>'),
            ('apex:include\tVF', 'apex:include pageName="$1"/>'),
            ('apex:includeScript\tVF', 'apex:includeScript value="$1"/>'),
            ('apex:inlineEditSupport\tVF', 'apex:inlineEditSupport showOnEdit="$1" cancelButton="$2" hideOnEdit="$3" event="$4"/>'),
            ('apex:inputCheckbox\tVF', 'apex:inputCheckbox value="$1"/>'),
            ('apex:inputField\tVF', 'apex:inputField value="$1"/>'),
            ('apex:inputHidden\tVF', 'apex:inputHidden value="$1"/>'),
            ('apex:inputSecret\tVF', 'apex:inputSecret value="$1"/>'),
            ('apex:inputText\tVF', 'apex:inputText value="$1"/>'),
            ('apex:inputTextarea\tVF', 'apex:inputTextarea value="$1"/>'),
            ('apex:insert\tVF', 'apex:insert name="$1"/>'),
            ('apex:listViews\tVF', 'apex:listViews name="$1"/>'),
            ('apex:message\tVF', 'apex:message for="$1"/>'),
            ('apex:messages\tVF', 'apex:messages />'),
            ('apex:outputField\tVF', 'apex:outputField value="$1"/>'),
            ('apex:outputLabel\tVF', 'apex:outputLabel value="$1" for="$2"/>'),
            ('apex:outputLink\tVF', 'apex:outputLink value="$1"/>'),
            ('apex:outputPanel\tVF', 'apex:outputPanel id="$1">\n\t$2\n</apex:outputPanel>'),
            ('apex:outputText\tVF', 'apex:outputText value="$1"/>'),
            ('apex:page\tVF', 'apex:page id="$1">\n\t$2\n</apex:page>'),
            ('apex:pageBlock\tVF', 'apex:pageBlock mode=\"${1:detail}\">\n\t$2\n</apex:pageBlock>'),
            ('apex:pageBlockButtons\tVF', 'apex:pageBlockButtons>\n\t$1\n</apex:pageBlockButtons>'),
            ('apex:pageBlockSection\tVF', 'apex:pageBlockSection title="$1" columns="$2">\n\t$3\n</apex:pageBlockSection>'),
            ('apex:pageBlockSectionItem\tVF', 'apex:pageBlockSectionItem>\n\t$1\n</apex:pageBlockSectionItem>'),
            ('apex:pageBlockTable\tVF', 'apex:pageBlockTable value="$1" var="$2">\n\t$3\n</apex:pageBlockTable>'),
            ('apex:pageMessage\tVF', 'apex:pageMessage summary="$1" serverity="$2" strength=\"${3:3}\"/>'),
            ('apex:pageMessages\tVF', 'apex:pageMessages />'),
            ('apex:panelBar\tVF', 'apex:panelBar>\n\t$1\n</apex:panelBar>'),
            ('apex:panelBarItem\tVF', 'apex:panelBarItem label="$1">$2<apex:panelBarItem/>'),
            ('apex:panelGrid\tVF', 'apex:panelGrid columns="$1">\n\t$2\n</apex:panelGrid>'),
            ('apex:panelGroup\tVF', 'apex:panelGroup id="$1">\n\t$2\n</apex:panelGroup>'),
            ('apex:param\tVF', 'apex:param value="$1"/>'),
            ('apex:relatedList\tVF', 'apex:relatedList list="$1"/>'),
            ('apex:repeat\tVF', 'apex:repeat value="$1" var="$2">\n\t$3\n</apex:repeat>'),
            ('apex:selectCheckboxes\tVF', 'apex:selectCheckboxes value="$1">\n\t$2\n</apex:selectCheckboxes>'),
            ('apex:selectList\tVF', 'apex:selectList value="$1" size="$2">\n\t$3\n</apex:selectList>'),
            ('apex:selectOption\tVF', 'apex:selectOption itemValue="$1" itemLabel="$2"/>'),
            ('apex:selectOptions\tVF', 'apex:selectOptions value="$1"/>'),
            ('apex:selectRadio\tVF', 'apex:selectRadio value="$1">\n\t$2\n</apex:selectRadio>'),
            ('apex:stylesheet\tVF', 'apex:stylesheet value="$1"/>'),
            ('apex:tab\tVF', 'apex:tab label="$1" name="$2"/>'),
            ('apex:tabPanel\tVF', 'apex:tabPanel>\n\t$2\n</apex:tabPanel>'),
            ('apex:toolbarGroup\tVF', 'apex:toolbarGroup itemSeparator="$1" id="$2">\n\t$3\n</apex:toolbarGroup>'),
            ('apex:variable\tVF', 'apex:variable var="$1" value="$2"/>'),
            ('apex:vote\tVF', 'apex:vote objectId="$1"/>')

        ], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)