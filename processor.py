import sublime
import sublime_plugin
import os
import urllib
import json
import threading
import time
import pprint
import base64
import zipfile
import shutil
import sys

try:
    # Python 3.x
    import urllib.parse
    from . import requests
    from . import context
    from .salesforce import util

    from .context import COMPONENT_METADATA_SETTINGS
    from .salesforce import message
    from .salesforce.api import SalesforceApi
    from xml.sax.saxutils import unescape
    from .salesforce.util import getUniqueElementValueFromXmlString
    from .salesforce import bulkapi
except:
    # Python 2.x
    import urllib
    import requests
    import context
    from salesforce import util
    from context import COMPONENT_METADATA_SETTINGS
    from salesforce import message
    from salesforce.api import SalesforceApi
    from xml.sax.saxutils import unescape
    from salesforce.util import getUniqueElementValueFromXmlString
    from salesforce import bulkapi


class ViewCommand(sublime_plugin.TextCommand):
    """
    Create a new view with specified input

    @input: user specified input

    Usage: 
        sublime.active_window().run_command("view", {
            "input": "Example"
        })
    """

    def run(self, edit, input=""):
        n = sublime.active_window().new_file()
        n.set_scratch(True)
        n.insert(edit, 0, input)

def populate_classes():
    """
    Get dict (Class Name => Class Id) which NamespacePrefix is null in whole org

    @return: {
        classname: classid
        ...
    }
    """
    # Get username
    toolingapi_settings = context.get_toolingapi_settings()
    username = toolingapi_settings["username"]

    # If sobjects is exist in globals()[], just return it
    if (username + "classes") in globals(): 
        return globals()[username + "classes"]

    # If sobjects is not exist in globals(), post request to pouplate it
    api = SalesforceApi(toolingapi_settings)
    query = "SELECT Id, Name FROM ApexClass WHERE NamespacePrefix = null"
    thread = threading.Thread(target=api.query_all, args=(query, ))
    thread.start()

    while thread.is_alive() or api.result == None:
        time.sleep(1)

    classes = {}
    for record in api.result["records"]:
        classes[record["Name"]] = record["Id"]
    
    globals()[username + "classes"] = classes
    return classes

def populate_sobject_recordtypes():
    """
    Get dict ([sobject, recordtype name] => recordtype id) in whole org

    @return: {
        username + "sobject_recordtypes": {
            sobject + rtname: rtid
        }
        ...
    }
    """

    # Get username
    toolingapi_settings = context.get_toolingapi_settings()
    username = toolingapi_settings["username"]

    # If sobjects is exist in globals()[], just return it
    if (username + "sobject_recordtypes") in globals(): 
        return globals()[username + "sobject_recordtypes"]

    # If sobjects is not exist in globals(), post request to pouplate it
    api = SalesforceApi(toolingapi_settings)
    query = "SELECT Id, Name, SobjectType FROM RecordType"
    thread = threading.Thread(target=api.query_all, args=(query, ))
    thread.start()

    while thread.is_alive() or api.result == None:
        time.sleep(1)

    records = api.result["records"]
    sobject_recordtypes = {}
    for recordtype in records:
        sobjectype = recordtype["SobjectType"]
        rtname = recordtype["Name"]
        rtid = recordtype["Id"]
        sobject_recordtypes[sobjectype + ", " + rtname] = rtid

    globals()[username + "sobject_recordtypes"] = sobject_recordtypes
    return sobject_recordtypes  

def populate_sobjects():
    """
    Get the sobjects list in org.
    """

    # Get username
    toolingapi_settings = context.get_toolingapi_settings()
    username = toolingapi_settings["username"]

    # If sobjects is exist in globals()[], just return it
    if (username + "sobjects") in globals(): 
        return globals()[username + "sobjects"]

    # If sobjects is not exist in globals(), post request to pouplate it
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.describe_global, args=())
    thread.start()

    while thread.is_alive() or api.result == None:
        time.sleep(1)

    sobjects = []
    for sobject in api.result["sobjects"]:
        sobjects.append(sobject["name"])

    globals()[username + "sobjects"] = sobjects
    return sobjects

def handle_backup_all_sobjects(timeout):
    """
    Firstly get all common used sobject names, and then use bulkapi to backup all
    """

    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return

        sobjects = api.result
        bulkapi.handle_bulkapi_query(sobjects)

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.describe_global_common, args=())
    thread.start()
    handle_thread(thread, 10)

def handle_initiate_sobjects_completions(timeout):
    """
    Save sobject describe to local which is used in completions
    """

    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda:handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.error_message(message.AUTHORIZATION_FAILED_MESSAGE)
            return
        
        # If succeed
        result = api.result
        s = sublime.load_settings("sobjects_completion.sublime-settings")

        sobjects_completion = {}
        for sobject_describe in result:
            # Combine fields dict
            fields_dict = {}

            if "fields" not in sobject_describe:
                print ("Things need to check......: " + sobject_describe)
                continue

            for f in sobject_describe["fields"]:
                fields_dict[f["name"] + " (" + f["type"] + ")"] = f["name"]
            
            # Combine sobject fields dict
            sobjects_completion[sobject_describe["name"]] = fields_dict

        # Every project has unique username
        username = toolingapi_settings["username"]
        s.set(username, sobjects_completion)

        # Save settings
        sublime.save_settings("sobjects_completion.sublime-settings")

    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.initiate_sobject_completion, args=())
    thread.start()
    handle_thread(thread, timeout)

def handle_retrieve_all_thread(timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda:handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.error_message(message.AUTHORIZATION_FAILED_MESSAGE)
            return
        
        result = api.result
        status_code = result["status_code"]
        
        if status_code > 399:
            util.sublime_error_message(result)
            return

        base64String = result["zipFile"]
        outputdir = toolingapi_settings["workspace"] + "/metadata"
        if not os.path.exists(outputdir):
            os.makedirs(outputdir)

        output_file_dir = outputdir + "/sobjects.zip"
        with open(output_file_dir, "wb") as fout:
            fout.write(base64.b64decode(base64String))
            fout.close()

        # Unzip sobjects.zip to file
        zipdir = toolingapi_settings["workspace"] + "/metadata/sobjects.zip"
        outputdir = toolingapi_settings["workspace"] + "/metadata"
        f = zipfile.ZipFile(zipdir, 'r')
        for fileinfo in f.infolist():
            path = outputdir
            directories = fileinfo.filename.split('/')
            for directory in directories:
                # replace / to &, because there has problem in open method
                try:
                    quoted_dir = urllib.parse.unquote(directory).replace("/", "&")
                except:
                    quoted_dir = urllib.unquote(directory).replace("/", "&")
                path = os.path.join(path, quoted_dir)
                if directory == directories[-1]: break # the file
                if not os.path.exists(path):
                    os.makedirs(path)

            outputfile = open(path, "wb")
            shutil.copyfileobj(f.open(fileinfo.filename), outputfile)
            outputfile.close()

        # Close zipFile opener
        f.close()

        # Remove this zip file
        os.remove(zipdir)

        # Output package path
        print("Your objects and workflows are exported to: " + outputdir)

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.retrieve_all, args=())
    thread.start()
    handle_thread(thread, timeout)

def handle_parse_workflow(timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        sobjects = api.result
        for sobject in sobjects:
            util.parse_workflow_metadata(toolingapi_settings, sobject)

        print("Your workflows are exported to " +\
            toolingapi_settings["workspace"] + "/describe/workflows/")

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.describe_global_common, args=())
    thread.start()
    handle_thread(thread, 10)

def handle_parse_validation_rule(timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return

        # If succeed
        sobjects = api.result
        util.parse_validation_rule(toolingapi_settings, sobjects)

        print("Your validation rules are exported to " +\
            toolingapi_settings["workspace"] + "/describe/validation rules/validation rules.csv")

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.describe_global_common, args=())
    thread.start()
    handle_thread(thread, 10)

def handle_describe_customfield(sobject, timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        # If error
        if result["status_code"] > 399 :
            util.sublime_error_message(result)
            return

        # Get output csv dir
        workspace = context.get_toolingapi_settings().get("workspace")
        outputdir = workspace + "/describe/customfield"
        if not os.path.exists(outputdir):
            os.makedirs(outputdir)

        # Open output csv
        output_file_dir = outputdir + "/" + sobject + ".csv"
        if util.is_python3x():
            fp = open(output_file_dir, "w", newline='')
        else:
            fp = open(output_file_dir, "wb")

        # Write list to csv
        util.list2csv(fp, result["records"])

        # Release fp
        fp.close()

        # Output log
        print(output_file_dir)

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    query = """SELECT Id,TableEnumOrId,DeveloperName,NamespacePrefix,FullName 
               FROM CustomField 
               WHERE TableEnumOrId='{sobject}'""".format(sobject=sobject)
    thread = threading.Thread(target=api.query_all, args=(query, True,))
    thread.start()
    handle_thread(thread, 10)

def handle_describe_global():
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        # If error
        if result["status_code"] > 399 :
            util.sublime_error_message(result)
            return

        # Get output csv dir
        workspace = context.get_toolingapi_settings().get("workspace")
        outputdir = workspace + "/describe/global"
        if not os.path.exists(outputdir):
            os.makedirs(outputdir)

        # Open output csv
        output_file_dir = outputdir + "/sobjects.csv"
        if util.is_python3x():
            fp = open(output_file_dir, "w", newline='')
        else:
            fp = open(output_file_dir, "wb")

        # Write list to csv
        util.list2csv(fp, result["sobjects"])

        # Output log
        print("global describe csv outputdir: " + output_file_dir)

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.describe_global, args=())
    thread.start()
    handle_thread(thread, 10)

def handle_describe_layout(sobject, recordtype_name, recordtype_id):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        
        # If error
        if result["status_code"] > 399 :
            util.sublime_error_message(result)
            return

        # If totalSize is 0
        if "totalSize" in result and result["totalSize"] == 0 :
            util.sublime_error_message(result)
            return

        # Get output csv dir
        toolingapi_settings = context.get_toolingapi_settings()
        outputdir = toolingapi_settings["workspace"] + "/describe/layout"

        # If outputdir is not exist, just make it
        if not os.path.exists(outputdir):
            os.makedirs(outputdir)

        output_file_dir = outputdir + "/" + sobject + "-" + recordtype_name + ".csv"

        if util.is_python3x():
            fp = open(output_file_dir, "w", newline='')
        else:
            fp = open(output_file_dir, "wb")
        util.parse_describe_layout_result(fp, result)
        
        print("Layout describe outputdir: " + output_file_dir)

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.describe_layout, args=(sobject, recordtype_id, ))
    thread.start()
    handle_thread(thread, 10)

def handle_execute_query(soql, timeout):
    def handle_new_view_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_new_view_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        # If error
        if result["status_code"] > 399:
            util.sublime_error_message(result)
            return None

        # No error, just display log in a new view
        sublime.active_window().run_command("view", {
            "input": util.parse_execute_query_result(result)
        })

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.query, args=(soql, ))
    thread.start()
    handle_new_view_thread(thread, timeout)

def handle_execute_anonymous(apex_string, timeout):
    def handle_new_view_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_new_view_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        # If error
        if result["status_code"] > 399:
            sublime.error_message(result["errorCode"] + "\n" + result["message"])
            return

        # No error, just display log in a new view
        sublime.active_window().run_command("view", {
            "input": util.parse_execute_anonymous_xml(result)
        })

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.execute_anonymous, args=(apex_string, ))
    thread.start()
    handle_new_view_thread(thread, timeout)

def handle_run_test(class_id, timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        # If error
        if "status_code" in result and result["status_code"] > 399:
            util.sublime_error_message(result)
            return

        # No error, just display log in a new view
        test_result = util.parse_test_result(result)

        # Sometimes, the test result will not show
        print (test_result)
        sublime.active_window().run_command("view", {
            "input": test_result
        })
            
    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.run_test, args=(class_id, ))
    thread.start()
    handle_thread(thread, timeout)

def handle_retrieve_fields(sobject, timeout):
    def handle_new_view_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_new_view_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        # If error
        if result["status_code"] > 399:
            util.sublime_error_message(result)
            return

        # No error, just display log in a new view
        sublime.active_window().run_command("view", {
            "input": util.parse_sobject_field_result(result)
        })

    print(message.WAIT_FOR_A_MOMENT)
    # Combine sobject url
    sobject_url = "/services/data/v27.0/sobjects/" + sobject+ "/describe"
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.get, args=(sobject_url, ))
    thread.start()
    handle_new_view_thread(thread, timeout)

def handle_generate_specified_workbooks(sobjects, timeout):
    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    threads = []
    for sobject in sobjects:
        thread = threading.Thread(target=api.generate_workbook, args=(sobject, ))
        threads.append(thread)
        thread.start()

def handle_generate_all_workbooks(timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        for sobject in result:
            thread = threading.Thread(target=api.generate_workbook, args=(sobject, ))
            thread.start()

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.describe_global_common, args=())
    thread.start()
    handle_thread(thread, timeout)

def handle_refresh_components(toolingapi_settings, timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda: handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.status_message(message.TOOLING_API_CONNECTING_FAILED)
            return
        
        # If succeed
        result = api.result
        # Load COMPONENT_METADATA_SETTINGS Settings and put all result into it
        component_metadta = sublime.load_settings(COMPONENT_METADATA_SETTINGS)
        for component in result.keys():
            component_metadta.set(component, result[component])

        # Save settings
        sublime.save_settings(COMPONENT_METADATA_SETTINGS)
        sublime.message_dialog(message.DOWNLOAD_ALL_SUCCESSFULLY)

    api = SalesforceApi(toolingapi_settings)
    component_types = context.get_toolingapi_settings()["component_types"]
    thread = threading.Thread(target=api.refresh_components, 
        args=(component_types, ))
    thread.start()
    handle_thread(thread, timeout)

def handle_save_component(data, component_type, component_id, body, timeout):
    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.save_component, 
        args=(data, component_type, component_id, body, ))
    thread.start()

def handle_create_component(data, component_name, component_type, timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda:handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.error_message(message.AUTHORIZATION_FAILED_MESSAGE)
            return
        
        # If create Succeed
        result = api.result
        status_code = result["status_code"]
        
        if status_code > 399:
            util.sublime_error_message(result)
            return
        
        # Get the created component id
        component_id = result.get("id")
        
        # Save it to component.sublime-settings
        s = sublime.load_settings(COMPONENT_METADATA_SETTINGS)
        s.set(component_type + component_name, {
            "component_id": component_id,
            "component_url": post_url + "/" + component_id
        })

        # Save settings and show success message
        sublime.save_settings(COMPONENT_METADATA_SETTINGS)
        sublime.message_dialog(message.CREATE_SUCCESSFULLY)
                
    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    post_url = "/services/data/v27.0/sobjects/" + component_type
    thread = threading.Thread(target=api.post, args=(post_url, data, ))
    thread.start()
    handle_thread(thread, timeout)

def handle_refresh_component(component_url, file_name, component_body, timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda:handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.error_message(message.AUTHORIZATION_FAILED_MESSAGE)
            return
        
        result = api.result
        status_code = result["status_code"]
        
        if status_code > 399:
            util.sublime_error_message(result)
            return

        fp = open(file_name, "wb")
        try:
            body = bytes(result["component_body"], "UTF-8")
        except:
            body = result[component_body].encode("UTF-8")

        fp.write(body)
        sublime.message_dialog(message.GET_SUCCESSFULLY)

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.get, args=(component_url, ))
    thread.start()
    handle_thread(thread, timeout)

def handle_delete_component(component_url, file_name, timeout):
    def handle_thread(thread, timeout):
        if thread.is_alive():
            sublime.set_timeout(lambda:handle_thread(thread, timeout), timeout)
            return
        elif api.result == None:
            sublime.error_message(message.AUTHORIZATION_FAILED_MESSAGE)
            return

        # If succeed
        result = api.result
        print (result)
        if result["status_code"] > 399:
            util.sublime_error_message(result)
            return

        os.remove(file_name)
        sublime.active_window().run_command("close")
        sublime.message_dialog(message.DELETE_SUCCESSFULLY)

    print(message.WAIT_FOR_A_MOMENT)
    toolingapi_settings = context.get_toolingapi_settings()
    api = SalesforceApi(toolingapi_settings)
    thread = threading.Thread(target=api.delete, args=(component_url, ))
    thread.start()
    handle_thread(thread, timeout)